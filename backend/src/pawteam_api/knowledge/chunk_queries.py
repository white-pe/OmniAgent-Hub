"""Read chunk sets and their paginated chunks."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.knowledge.documents import (
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeChunkPage,
    KnowledgeChunkResponse,
    KnowledgeChunkSetSummary,
)
from pawteam_api.models import (
    KnowledgeChunk,
    KnowledgeChunkSet,
    KnowledgeDocumentVersion,
)


class KnowledgeChunkSetNotFoundError(ValueError):
    """指定版本下不存在该切块批次。"""


class KnowledgeChunkQueryService:
    """只查询已经保存的切块结果，不隐式执行解析或切块。"""

    def __init__(self, session: AsyncSession) -> None:
        # 与项目现有查询模式一致：请求依赖提供 Session，
        # 当前 Service 不自行提交事务，也不保存跨请求状态。
        self.session = session

    async def list_chunk_sets(
        self,
        document_id: str,
        version_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[KnowledgeChunkSetSummary]:
        """分页查询指定版本下的批次，仅返回元信息。"""

        self._validate_pagination(limit, offset)
        await self._require_version(document_id, version_id)

        records = (
            await self.session.scalars(
                select(KnowledgeChunkSet)
                .where(KnowledgeChunkSet.version_id == version_id)
                .order_by(
                    KnowledgeChunkSet.created_at.desc(),
                    KnowledgeChunkSet.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()

        # 时间可能相同，因此增加唯一 ID 作为第二排序条件。
        # 此处没有查询 KnowledgeChunk，自然不会加载片段正文。
        return [
            KnowledgeChunkSetSummary.model_validate(record)
            for record in records
        ]

    async def get_chunk_set(
        self,
        document_id: str,
        version_id: str,
        chunk_set_id: str,
    ) -> KnowledgeChunkSetSummary:
        """返回指定批次的元信息，并验证完整的父子资源关系。"""

        record = await self._require_chunk_set(
            document_id,
            version_id,
            chunk_set_id,
        )
        return KnowledgeChunkSetSummary.model_validate(record)

    async def list_chunks(
        self,
        document_id: str,
        version_id: str,
        chunk_set_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> KnowledgeChunkPage:
        """按片段编号升序读取一页正文。"""

        self._validate_pagination(limit, offset)

        # 必须先检查批次归属。
        # 不能只凭 chunk_set_id 查询正文，否则 URL 中的父资源会失去约束。
        await self._require_chunk_set(
            document_id,
            version_id,
            chunk_set_id,
        )

        total = await self.session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
        )

        records = (
            await self.session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
                .order_by(KnowledgeChunk.chunk_index)
                .limit(limit)
                .offset(offset)
            )
        ).all()

        return KnowledgeChunkPage(
            chunk_set_id=chunk_set_id,
            total=int(total or 0),
            limit=limit,
            offset=offset,
            items=[
                KnowledgeChunkResponse.model_validate(
                    record,
                    from_attributes=True,
                )
                for record in records
            ],
        )

    async def _require_version(
        self,
        document_id: str,
        version_id: str,
    ) -> None:
        """检查版本存在，且确实属于指定文档。"""

        existing_id = await self.session.scalar(
            select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.id == version_id,
                KnowledgeDocumentVersion.document_id == document_id,
            )
        )
        if existing_id is None:
            raise KnowledgeDocumentVersionNotFoundError(version_id)

    async def _require_chunk_set(
        self,
        document_id: str,
        version_id: str,
        chunk_set_id: str,
    ) -> KnowledgeChunkSet:
        """检查 document → version → chunk_set 的完整关系。"""

        await self._require_version(document_id, version_id)

        record = await self.session.scalar(
            select(KnowledgeChunkSet).where(
                KnowledgeChunkSet.id == chunk_set_id,
                KnowledgeChunkSet.version_id == version_id,
            )
        )
        if record is None:
            # 批次不存在、批次属于其他版本，统一视为当前路径下不存在。
            raise KnowledgeChunkSetNotFoundError(chunk_set_id)

        return record

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        """保护内部调用，避免只有 HTTP 入口限制分页参数。"""

        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("Offset must be non-negative")