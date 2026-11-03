"""HTTP endpoints for saved knowledge chunk results."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.knowledge.chunk_queries import (
    KnowledgeChunkQueryService,
    KnowledgeChunkSetNotFoundError,
)
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeChunkPage,
    KnowledgeChunkSetSummary,
)


router = APIRouter(
    prefix="/knowledge-documents",
    tags=["knowledge-chunks"],
)

SessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]

# 三个端点共用分页参数定义，避免各自采用不同范围。
LimitParameter = Annotated[int, Query(ge=1, le=100)]
OffsetParameter = Annotated[int, Query(ge=0)]


def translate_query_error(
    error: KnowledgeDocumentVersionNotFoundError
    | KnowledgeChunkSetNotFoundError,
) -> HTTPException:
    """只转换预期的资源不存在错误，不吞掉数据库等意外故障。"""

    if isinstance(error, KnowledgeDocumentVersionNotFoundError):
        return HTTPException(
            status_code=404,
            detail="Document version not found",
        )

    return HTTPException(
        status_code=404,
        detail="Chunk set not found",
    )


@router.get(
    "/{document_id}/versions/{version_id}/chunk-sets",
    response_model=list[KnowledgeChunkSetSummary],
)
async def list_chunk_sets(
    document_id: str,
    version_id: str,
    session: SessionDependency,
    limit: LimitParameter = 20,
    offset: OffsetParameter = 0,
) -> list[KnowledgeChunkSetSummary]:
    """查询批次列表；没有切块结果时返回空列表。"""

    try:
        return await KnowledgeChunkQueryService(session).list_chunk_sets(
            document_id,
            version_id,
            limit=limit,
            offset=offset,
        )
    except KnowledgeDocumentVersionNotFoundError as error:
        raise translate_query_error(error) from error


@router.get(
    "/{document_id}/versions/{version_id}/chunk-sets/{chunk_set_id}",
    response_model=KnowledgeChunkSetSummary,
)
async def get_chunk_set(
    document_id: str,
    version_id: str,
    chunk_set_id: str,
    session: SessionDependency,
) -> KnowledgeChunkSetSummary:
    """查询单个批次参数，不附带整批正文。"""

    try:
        return await KnowledgeChunkQueryService(session).get_chunk_set(
            document_id,
            version_id,
            chunk_set_id,
        )
    except (
        KnowledgeDocumentVersionNotFoundError,
        KnowledgeChunkSetNotFoundError,
    ) as error:
        raise translate_query_error(error) from error


@router.get(
    "/{document_id}/versions/{version_id}/chunk-sets/{chunk_set_id}/chunks",
    response_model=KnowledgeChunkPage,
)
async def list_chunks(
    document_id: str,
    version_id: str,
    chunk_set_id: str,
    session: SessionDependency,
    limit: LimitParameter = 20,
    offset: OffsetParameter = 0,
) -> KnowledgeChunkPage:
    """查询一页片段，分页越界时 items 为空，total 保持实际总数。"""

    try:
        return await KnowledgeChunkQueryService(session).list_chunks(
            document_id,
            version_id,
            chunk_set_id,
            limit=limit,
            offset=offset,
        )
    except (
        KnowledgeDocumentVersionNotFoundError,
        KnowledgeChunkSetNotFoundError,
    ) as error:
        raise translate_query_error(error) from error