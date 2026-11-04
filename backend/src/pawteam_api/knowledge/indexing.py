"""将关系数据库中已保存的向量幂等同步到 Qdrant。"""

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


class VectorIndexSourceError(RuntimeError):
    """数据库中的向量来源不完整或与索引配置不匹配。"""


@dataclass(frozen=True)
class VectorIndexResult:
    """一次同步操作的摘要，不返回高维向量数据。"""

    profile_id: str
    chunk_set_id: str
    point_count: int


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

        # Session 已关闭后再访问 Qdrant，避免网络 I/O 占用数据库连接。
        # 必须先验证集合配置；适配器不会自动删除或重建不兼容集合。
        await self.vector_store.initialize()

        # Qdrant upsert 使用 chunk UUID 作为固定点 ID。
        # 整批重试时会覆盖相同 ID，不会重复创建点。
        # 任何一批失败都向上传播；调用方可安全地重试整个切块批次。
        batch_size = self.vector_store.max_upsert_points
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            await self.vector_store.upsert(batch)

        return VectorIndexResult(
            profile_id=profile_id,
            chunk_set_id=chunk_set_id,
            point_count=len(points),
        )
