"""发布只更新权威指针，旧索引保留供恢复，在线检索严格按指针过滤。"""

from datetime import UTC, datetime

from sqlalchemy import func, select

from pawteam_api.knowledge.rag_schemas import PublicationResponse
from pawteam_api.models import (
    KnowledgeChunk, KnowledgeChunkEmbedding, KnowledgeChunkSet,
    KnowledgeDocument, KnowledgeDocumentVersion, KnowledgePublication,
    KnowledgeVectorIndex,
)


class PublicationConflictError(ValueError):
    pass


async def publish(session, *, document_id: str, chunk_set_id: str, profile_id: str):
    """由调用方提交事务；任务完成状态与发布指针可以在同一事务更新。"""

    document = await session.get(KnowledgeDocument, document_id)
    source = await session.scalar(
        select(KnowledgeChunkSet.id)
        .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeChunkSet.version_id)
        .where(KnowledgeChunkSet.id == chunk_set_id, KnowledgeDocumentVersion.document_id == document_id)
    )
    state = await session.get(KnowledgeVectorIndex, (profile_id, chunk_set_id))
    total = await session.scalar(
        select(func.count()).select_from(KnowledgeChunk)
        .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
    )
    saved = await session.scalar(
        select(func.count()).select_from(KnowledgeChunkEmbedding)
        .join(KnowledgeChunk, KnowledgeChunk.id == KnowledgeChunkEmbedding.chunk_id)
        .where(KnowledgeChunk.chunk_set_id == chunk_set_id,
               KnowledgeChunkEmbedding.profile_id == profile_id)
    )
    if document is None or document.status != "active" or not source:
        raise PublicationConflictError("Active document and matching chunk set required")
    if (
        state is None or state.status != "indexed" or not total
        or state.indexed_points != total or state.expected_points != total
        or saved != total
    ):
        raise PublicationConflictError("Complete embeddings and index required before publication")
    record = await session.get(KnowledgePublication, document_id)
    if record is None:
        record = KnowledgePublication(
            document_id=document_id, profile_id=profile_id, chunk_set_id=chunk_set_id
        )
        session.add(record)
    else:
        record.profile_id = profile_id
        record.chunk_set_id = chunk_set_id
        record.updated_at = datetime.now(UTC)
    await session.flush()
    return PublicationResponse.model_validate(record)
