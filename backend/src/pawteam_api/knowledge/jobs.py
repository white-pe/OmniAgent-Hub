"""单进程、持久化任务编排。每个阶段复用已有业务服务，不持有长事务。"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from pawteam_api.knowledge.embedding_persistence import KnowledgeEmbeddingPersistenceService
from pawteam_api.knowledge.indexing import KnowledgeVectorIndexingService
from pawteam_api.knowledge.publication import publish
from pawteam_api.knowledge.rag_schemas import IngestionRequest
from pawteam_api.knowledge.vector_store import QdrantVectorStore
from pawteam_api.models import KnowledgeEmbeddingProfile, KnowledgeIngestionJob, KnowledgeVectorIndex

logger = logging.getLogger(__name__)


class JobCancelledError(RuntimeError):
    pass


class KnowledgeJobManager:
    def __init__(self, *, session_factory, settings, secret_store, parsing_service,
                 chunking_service, retrieval_service):
        self.session_factory = session_factory
        self.settings = settings
        self.secret_store = secret_store
        self.parsing_service = parsing_service
        self.chunking_service = chunking_service
        self.retrieval_service = retrieval_service
        self.tasks = {}
        self.semaphore = asyncio.Semaphore(settings.knowledge_job_concurrency)

    async def recover(self):
        try:
            async with self.session_factory.begin() as session:
                # 明确采用单进程部署。重启时在途任务标为失败，
                # 不猜测外部模型是否已执行；重试复用已持久化阶段。
                await session.execute(update(KnowledgeIngestionJob).where(
                    KnowledgeIngestionJob.status == "running"
                ).values(status="failed", active_key=None,
                         error_message="服务重启中断任务，请检查后重试"))
                queued = list((await session.scalars(
                    select(KnowledgeIngestionJob.id)
                    .where(KnowledgeIngestionJob.status == "queued")
                )).all())
        except OperationalError as error:
            if "no such table" not in str(error):
                raise
            return
        for job_id in queued:
            self.start(job_id)

    def start(self, job_id):
        if job_id in self.tasks:
            return
        task = asyncio.create_task(self._execute(job_id), name=f"knowledge-{job_id}")
        self.tasks[job_id] = task
        task.add_done_callback(lambda done: self.tasks.pop(job_id, None))

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel(self, job_id):
        async with self.session_factory.begin() as session:
            job = await session.get(KnowledgeIngestionJob, job_id)
            if job and job.status in ("queued", "running"):
                job.cancel_requested = True
        # 在阶段边界协作取消，不在远端调用或数据库 commit 中途强制切断。
        # 因此取消请求不承诺撤销已经产生的模型费用。

    async def _stage(self, job_id, stage, chunk_set_id=None):
        async with self.session_factory.begin() as session:
            job = await session.get(KnowledgeIngestionJob, job_id)
            if job is None or job.cancel_requested:
                raise JobCancelledError()
            job.stage = stage
            if chunk_set_id:
                job.chunk_set_id = chunk_set_id

    async def _finish(self, job_id, status, message=None):
        async with self.session_factory.begin() as session:
            job = await session.get(KnowledgeIngestionJob, job_id)
            if job and job.status in ("queued", "running"):
                job.status = status
                job.active_key = None
                job.error_message = message

    async def _execute(self, job_id):
        try:
            async with self.semaphore:
                async with self.session_factory.begin() as session:
                    claimed = await session.execute(update(KnowledgeIngestionJob).where(
                        KnowledgeIngestionJob.id == job_id,
                        KnowledgeIngestionJob.status == "queued",
                    ).values(status="running"))
                    if claimed.rowcount != 1:
                        return
                    job = await session.get(KnowledgeIngestionJob, job_id)
                    document_id, version_id, profile_id = job.document_id, job.version_id, job.profile_id
                    config = IngestionRequest(
                        profile_id=profile_id, chunk_size=job.chunk_size,
                        chunk_overlap=job.chunk_overlap, rebuild=job.rebuild,
                    )
                async with asyncio.timeout(self.settings.knowledge_job_timeout_seconds):
                    await self._stage(job_id, "parsing")
                    await self.parsing_service.parse_version(
                        document_id=document_id, version_id=version_id
                    )
                    await self._stage(job_id, "chunking")
                    from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig
                    chunk_set = await self.chunking_service.create_chunk_set(
                        document_id=document_id, version_id=version_id,
                        config=KnowledgeChunkingConfig(
                            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap
                        ),
                    )
                    await self._stage(job_id, "embedding", chunk_set.id)
                    async with httpx.AsyncClient() as client:
                        await KnowledgeEmbeddingPersistenceService(
                            session_factory=self.session_factory,
                            secret_store=self.secret_store, http_client=client,
                            batch_size=self.settings.knowledge_embedding_batch_size,
                        ).embed_chunk_set(document_id, version_id, chunk_set.id, profile_id)
                    await self._stage(job_id, "indexing")
                    if config.rebuild:
                        # Qdrant 丢失后重建复用数据库向量，不再调用付费模型。
                        async with self.session_factory.begin() as session:
                            state = await session.get(KnowledgeVectorIndex, (profile_id, chunk_set.id))
                            if state and state.status == "indexing":
                                expiry = state.lease_until
                                if expiry and expiry.replace(tzinfo=UTC) > datetime.now(UTC):
                                    raise RuntimeError("Index lease is active")
                            if state:
                                state.status = "pending"
                                state.indexed_points = 0
                                state.lease_until = None
                                state.indexed_at = None
                    async with self.session_factory() as session:
                        profile = await session.get(KnowledgeEmbeddingProfile, profile_id)
                        dimensions = profile.dimensions
                    client = self.retrieval_service.qdrant()
                    try:
                        store = QdrantVectorStore(
                            client=client, profile_id=profile_id, dimensions=dimensions
                        )
                        indexed = await KnowledgeVectorIndexingService(
                            session_factory=self.session_factory, vector_store=store
                        ).index_chunk_set(profile_id=profile_id, chunk_set_id=chunk_set.id)
                        if await store.count_chunk_set(chunk_set.id) != indexed.point_count:
                            raise RuntimeError("Remote index incomplete; submit rebuild job")
                    finally:
                        await client.close()
                    await self._stage(job_id, "publishing")
                    async with self.session_factory.begin() as session:
                        current = await session.get(KnowledgeIngestionJob, job_id)
                        if current is None or current.cancel_requested:
                            raise JobCancelledError()
                        await publish(
                            session, document_id=document_id,
                            chunk_set_id=chunk_set.id, profile_id=profile_id,
                        )
                        current.status = "completed"
                        current.stage = "completed"
                        current.active_key = None
        except JobCancelledError:
            await self._finish(job_id, "cancelled")
        except asyncio.CancelledError:
            await self._finish(job_id, "failed", "服务停止中断任务，请检查后重试")
            raise
        except Exception as error:
            logger.exception("Knowledge job failed: job_id=%s", job_id)
            # 不保存上游响应、文件路径或密钥。具体堆栈仅在后端日志查看。
            message = (
                "任务超时，请检查状态后重试" if isinstance(error, TimeoutError)
                else f"处理失败（{type(error).__name__}），请查看后端日志"
            )
            await self._finish(job_id, "failed", message)
