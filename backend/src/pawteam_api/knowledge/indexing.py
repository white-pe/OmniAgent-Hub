"""将关系数据库中已保存的向量幂等同步到 Qdrant。"""
import asyncio

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.knowledge.embeddings import EmbeddingBatch
from pawteam_api.knowledge.vector_store import (
    QdrantVectorStore,
    VectorIndexPoint,
    VectorMetadata,
)
from pawteam_api.models import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeChunkSet,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
)
from pawteam_api.knowledge.index_state import (
    KnowledgeVectorIndexStateService,
)

class VectorIndexSourceError(RuntimeError):
    """数据库中的向量来源不完整或与索引配置不匹配。"""


@dataclass(frozen=True)
class VectorIndexResult:
    """一次同步操作的摘要，不返回高维向量数据。"""

    profile_id: str
    chunk_set_id: str
    point_count: int
    reused: bool = False


class KnowledgeVectorIndexingService:
    """读取已落库的向量，并按幂等点 ID 写入 Qdrant。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: QdrantVectorStore,
    ) -> None:
        # 每次数据库读取都使用独立 Session；
        # Service 不保存跨请求复用的 Session。
        self.session_factory = session_factory
        self.vector_store = vector_store
        self.index_state = KnowledgeVectorIndexStateService(session_factory)

    async def index_chunk_set(
        self,
        *,
        profile_id: str,
        chunk_set_id: str,
    ) -> VectorIndexResult:
        """把一个切块批次的完整向量集同步至对应 Profile 的集合。"""

        # 先从关系数据库读取并验证完整数据快照。
        # 在数据通过验证之前，不对 Qdrant 做任何写入。
        async with self.session_factory() as session:
            profile = await session.get(
                KnowledgeEmbeddingProfile,
                profile_id,
            )
            if profile is None:
                raise VectorIndexSourceError(
                    "Embedding profile does not exist"
                )

            # 确认注入的 Qdrant Store 与数据库 Profile 一致，
            # 防止配置错误时把向量写入另一个集合。
            if (
                self.vector_store.profile_id != UUID(profile_id)
                or self.vector_store.dimensions != profile.dimensions
            ):
                raise VectorIndexSourceError(
                    "Qdrant store does not match embedding profile"
                )

            # 先统计切块总数，再与向量查询结果数量比较。
            # 只查询已有向量会漏掉“部分向量缺失”的问题。
            expected_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
            )
            if not expected_count:
                raise VectorIndexSourceError(
                    "Chunk set does not exist or contains no chunks"
                )

            rows = (
                await session.execute(
                    select(
                        KnowledgeChunk.id,
                        KnowledgeChunkEmbedding.vector,
                        KnowledgeChunkSet.id,
                        KnowledgeDocumentVersion.id,
                        KnowledgeDocument.id,
                        KnowledgeDocument.knowledge_base_id,
                    )
                    .select_from(KnowledgeChunk)
                    .join(
                        KnowledgeChunkEmbedding,
                        KnowledgeChunkEmbedding.chunk_id
                        == KnowledgeChunk.id,
                    )
                    .join(
                        KnowledgeChunkSet,
                        KnowledgeChunkSet.id
                        == KnowledgeChunk.chunk_set_id,
                    )
                    .join(
                        KnowledgeDocumentVersion,
                        KnowledgeDocumentVersion.id
                        == KnowledgeChunkSet.version_id,
                    )
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id
                        == KnowledgeDocumentVersion.document_id,
                    )
                    .where(
                        KnowledgeChunk.chunk_set_id == chunk_set_id,
                        KnowledgeChunkEmbedding.profile_id == profile_id,
                    )
                    .order_by(KnowledgeChunk.chunk_index)
                )
            ).all()

            # 数量不一致可能表示向量化未完成、数据被删除，
            # 或者请求使用了错误的 Profile。不能同步部分数据。
            if len(rows) != expected_count:
                raise VectorIndexSourceError(
                    "Chunk set does not have a complete embedding set"
                )

            try:
                # 在写入 Qdrant 前，对数据库中取出的所有向量再做一次
                # 维度、有限数值和非零向量校验。
                validated = EmbeddingBatch(
                    dimensions=profile.dimensions,
                    vectors=[row[1] for row in rows],
                )
            except ValueError as error:
                raise VectorIndexSourceError(
                    "Stored embeddings failed validation"
                ) from error

            # 把数据库行转换成 Qdrant Adapter 接受的显式数据结构。
            # 正文不复制到 Qdrant，后续命中后再按 chunk_id 回查数据库。
            points = [
                VectorIndexPoint(
                    metadata=VectorMetadata(
                        profile_id=profile_id,
                        knowledge_base_id=row[5],
                        document_id=row[4],
                        version_id=row[3],
                        chunk_set_id=row[2],
                        chunk_id=row[0],
                    ),
                    vector=tuple(vector),
                )
                for row, vector in zip(
                    rows,
                    validated.vectors,
                    strict=True,
                )
            ]

        # 来源校验已完成，数据库 Session 已关闭。
        # 领取任务后才允许访问 Qdrant，不跨网络请求持有数据库事务。
        lease_seconds = 60
        attempt = await self.index_state.claim(
            profile_id=profile_id,
            chunk_set_id=chunk_set_id,
            lease_seconds=lease_seconds,
        )

        if attempt is None:
            # claim() 返回 None 表示数据库中已记录为 indexed。
            return VectorIndexResult(
                profile_id=profile_id,
                chunk_set_id=chunk_set_id,
                point_count=len(points),
                reused=True,
            )

        async def renew() -> None:
            """每次外部写入前，确认本轮执行仍拥有有效租约。"""

            await self.index_state.renew(
                profile_id=profile_id,
                chunk_set_id=chunk_set_id,
                attempt=attempt,
                lease_seconds=lease_seconds,
            )

        try:
            await renew()

            # 为单次外部操作设置短于租约的时间上限。
            # 避免请求长时间挂起，而任务一直被认为正在正常执行。
            async with asyncio.timeout(20):
                await self.vector_store.initialize()

            batch_size = self.vector_store.max_upsert_points

            for start in range(0, len(points), batch_size):
                # 旧任务失去租约时，在下一批写入前停止。
                await renew()

                async with asyncio.timeout(20):
                    await self.vector_store.upsert(
                        points[start: start + batch_size]
                    )

            # 完成网络写入后，再确认租约有效并留出收尾时间。
            await renew()

        except asyncio.CancelledError:
            # 调用被取消时保留取消语义。
            # 状态暂留 indexing，后续可在租约过期后重新领取。
            raise

        except Exception as error:
            try:
                await self.index_state.finish(
                    profile_id=profile_id,
                    chunk_set_id=chunk_set_id,
                    attempt=attempt,
                    succeeded=False,
                )
            except Exception:
                # 数据库异常或租约失效，可能导致失败状态也无法保存。
                # 保留原始执行错误，不让收尾错误把真正原因覆盖掉。
                error.add_note(
                    "Could not record index failure; "
                    "inspect task state and lease"
                )
            raise

        # 成功收尾放在上面的异常处理之外。
        # 若提交成功状态时发生数据库异常，不能再盲目覆盖为 failed。
        await self.index_state.finish(
            profile_id=profile_id,
            chunk_set_id=chunk_set_id,
            attempt=attempt,
            succeeded=True,
            point_count=len(points),
        )

        return VectorIndexResult(
            profile_id=profile_id,
            chunk_set_id=chunk_set_id,
            point_count=len(points),
        )
