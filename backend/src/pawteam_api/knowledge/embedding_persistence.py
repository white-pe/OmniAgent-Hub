"""Generate and persist embeddings for one complete chunk set."""

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.knowledge.embedding_client import CompatibleEmbeddingClient
from pawteam_api.knowledge.embedding_service import (
    EmbeddingChunkInput,
    KnowledgeEmbeddingService,
)
from pawteam_api.knowledge.embeddings import EmbeddingBatch
from pawteam_api.models import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeChunkSet,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
    Provider,
    ProviderModel,
)
from pawteam_api.security.secret_store import SecretStore


class EmbeddingSourceNotFoundError(LookupError):
    """当前路径下找不到切块批次，或找不到指定配置。"""


class EmbeddingPersistenceConflictError(RuntimeError):
    """配置、来源或已有结果不满足本次完整写入要求。"""


@dataclass(frozen=True)
class SavedEmbeddingResult:
    """返回执行摘要，不把整批向量作为操作响应返回。"""

    chunk_set_id: str
    profile_id: str
    chunk_count: int
    reused: bool


@dataclass(frozen=True)
class _EmbeddingSource:
    """从 ORM 中提取的普通值，用于模型调用前后的来源比较。"""

    provider_id: str
    base_url: str
    model_name: str
    model_revision: str
    dimensions: int
    send_dimensions: bool
    input_policy_version: str
    api_key_ref: str
    chunks: tuple[EmbeddingChunkInput, ...]


class KnowledgeEmbeddingPersistenceService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        secret_store: SecretStore,
        http_client: httpx.AsyncClient,
        batch_size: int = 32,
    ) -> None:
        # Service 保存组件引用，不保存跨请求共享的数据库 Session。
        self.session_factory = session_factory
        self.secret_store = secret_store
        self.http_client = http_client
        self.batch_size = batch_size

    async def embed_chunk_set(
        self,
        document_id: str,
        version_id: str,
        chunk_set_id: str,
        profile_id: str,
    ) -> SavedEmbeddingResult:
        """生成并保存整个批次；已经完整生成的结果直接复用。"""

        async with self.session_factory() as session:
            source = await self._read_source(
                session,
                document_id,
                version_id,
                chunk_set_id,
                profile_id,
            )

            if await self._has_complete_result(
                session,
                chunk_set_id,
                profile_id,
                source,
            ):
                return SavedEmbeddingResult(
                    chunk_set_id,
                    profile_id,
                    len(source.chunks),
                    reused=True,
                )

        # 到这里，读取 Session 已关闭。
        # 不在数据库事务中等待模型，避免占用连接或延长事务。
        api_key = self.secret_store.get(source.api_key_ref)

        client = CompatibleEmbeddingClient(
            http_client=self.http_client,
            base_url=source.base_url,
            api_key=api_key,
        )
        embedding_service = KnowledgeEmbeddingService(
            client=client,
            model=source.model_name,
            expected_dimensions=source.dimensions,
            send_dimensions=source.send_dimensions,
            batch_size=self.batch_size,
        )

        generated = await embedding_service.embed_chunks(list(source.chunks))

        # 明确检查生成结果与来源一一对应。
        # 不允许遗漏、重复或交换片段 ID。
        expected_ids = [chunk.chunk_id for chunk in source.chunks]
        if [item.chunk_id for item in generated] != expected_ids:
            raise EmbeddingPersistenceConflictError(
                "Generated embeddings do not match source chunks"
            )

        # 即使上游客户端已经校验，持久化入口仍校验最终待写入数据。
        # 以后替换批处理实现时，也不能绕过数据库写入边界。
        validated = EmbeddingBatch(
            dimensions=source.dimensions,
            vectors=[list(item.vector) for item in generated],
        )

        try:
            async with self.session_factory.begin() as session:
                current_source = await self._read_source(
                    session,
                    document_id,
                    version_id,
                    chunk_set_id,
                    profile_id,
                )

                # 比较普通值，而不是跨 Session 比较 ORM 对象。
                # 识别模型调用期间已经发生的配置、文本或片段关系变化。
                if current_source != source:
                    raise EmbeddingPersistenceConflictError(
                        "Embedding source changed during generation"
                    )

                # 其他请求可能已经完成，因此写入前再次检查。
                if await self._has_complete_result(
                    session,
                    chunk_set_id,
                    profile_id,
                    current_source,
                ):
                    return SavedEmbeddingResult(
                        chunk_set_id,
                        profile_id,
                        len(source.chunks),
                        reused=True,
                    )

                session.add_all(
                    [
                        KnowledgeChunkEmbedding(
                            profile_id=profile_id,
                            chunk_id=chunk.chunk_id,
                            vector=vector,
                        )
                        for chunk, vector in zip(
                            source.chunks,
                            validated.vectors,
                            strict=True,
                        )
                    ]
                )

                # 在事务中显式执行 INSERT，使约束错误在这里暴露。
                # 任意写入失败，本次事务内的所有向量一起回滚。
                await session.flush()

                return SavedEmbeddingResult(
                    chunk_set_id,
                    profile_id,
                    len(source.chunks),
                    reused=False,
                )
        except IntegrityError as error:
            # 不把唯一键或外键错误伪装成成功。
            # 退出 begin() 后，失败事务已经回滚。
            raise EmbeddingPersistenceConflictError(
                "Embedding write conflicted; inspect state before retrying"
            ) from error

    async def _read_source(
        self,
        session: AsyncSession,
        document_id: str,
        version_id: str,
        chunk_set_id: str,
        profile_id: str,
    ) -> _EmbeddingSource:
        """检查资源关系与配置，返回可跨会话使用的来源快照。"""

        chunk_set = await session.scalar(
            select(KnowledgeChunkSet)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeChunkSet.version_id,
            )
            .where(
                KnowledgeChunkSet.id == chunk_set_id,
                KnowledgeChunkSet.version_id == version_id,
                KnowledgeDocumentVersion.document_id == document_id,
            )
        )
        profile = await session.get(KnowledgeEmbeddingProfile, profile_id)

        if chunk_set is None or profile is None:
            raise EmbeddingSourceNotFoundError(
                "Chunk set or embedding profile not found"
            )

        provider = await session.get(Provider, profile.provider_id)
        if provider is None or not provider.enabled:
            raise EmbeddingPersistenceConflictError(
                "Embedding provider is unavailable"
            )

        if provider.kind != "openai_compatible":
            raise EmbeddingPersistenceConflictError(
                "Unsupported embedding provider kind"
            )

        # 允许基础地址末尾斜杠不同，不允许悄悄切换服务地址。
        if provider.base_url.rstrip("/") != profile.base_url.rstrip("/"):
            raise EmbeddingPersistenceConflictError(
                "Provider address no longer matches embedding profile"
            )

        model_id = await session.scalar(
            select(ProviderModel.id).where(
                ProviderModel.provider_id == provider.id,
                ProviderModel.model_name == profile.model_name,
                ProviderModel.enabled.is_(True),
            )
        )
        if model_id is None:
            raise EmbeddingPersistenceConflictError(
                "Embedding model is not registered or enabled"
            )

        if profile.input_policy_version != "raw-v1":
            raise EmbeddingPersistenceConflictError(
                "Unsupported embedding input policy"
            )

        records = (
            await session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
                .order_by(KnowledgeChunk.chunk_index)
                # 多读一条用于发现超限，避免无界读取记录。
                .limit(KnowledgeEmbeddingService.max_input_chunks + 1)
            )
        ).all()

        if not 1 <= len(records) <= KnowledgeEmbeddingService.max_input_chunks:
            raise EmbeddingPersistenceConflictError(
                "Chunk set is empty or exceeds the supported size"
            )

        return _EmbeddingSource(
            provider_id=provider.id,
            base_url=profile.base_url,
            model_name=profile.model_name,
            model_revision=profile.model_revision,
            dimensions=profile.dimensions,
            send_dimensions=profile.send_dimensions,
            input_policy_version=profile.input_policy_version,
            api_key_ref=provider.api_key_ref,
            chunks=tuple(
                EmbeddingChunkInput(chunk.id, chunk.text)
                for chunk in records
            ),
        )

    async def _has_complete_result(
        self,
        session: AsyncSession,
        chunk_set_id: str,
        profile_id: str,
        source: _EmbeddingSource,
    ) -> bool:
        """只有完整且有效的一组向量，才可以作为成功结果复用。"""

        records = (
            await session.scalars(
                select(KnowledgeChunkEmbedding)
                .join(
                    KnowledgeChunk,
                    KnowledgeChunk.id == KnowledgeChunkEmbedding.chunk_id,
                )
                .where(
                    KnowledgeChunk.chunk_set_id == chunk_set_id,
                    KnowledgeChunkEmbedding.profile_id == profile_id,
                )
                .order_by(KnowledgeChunk.chunk_index)
            )
        ).all()

        if not records:
            return False

        expected_ids = [chunk.chunk_id for chunk in source.chunks]
        actual_ids = [record.chunk_id for record in records]

        if actual_ids != expected_ids:
            raise EmbeddingPersistenceConflictError(
                "Existing embeddings are incomplete"
            )

        try:
            EmbeddingBatch(
                dimensions=source.dimensions,
                vectors=[record.vector for record in records],
            )
        except ValueError as error:
            raise EmbeddingPersistenceConflictError(
                "Existing embeddings failed validation"
            ) from error

        return True