"""HTTP endpoints for saved knowledge chunk results."""
import logging

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    KnowledgeChunkingConfig,
)
from pawteam_api.knowledge.chunk_service import (
    KnowledgeChunkingService,
    KnowledgeChunkSourceNotReadyError,
)
from pawteam_api.knowledge.chunking import KnowledgeChunkingLimitError


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


logger = logging.getLogger(__name__)


def get_chunking_service(request: Request) -> KnowledgeChunkingService:
    """取得启动时创建的 Service，不在依赖中打开写入会话。"""

    return request.app.state.knowledge_chunking_service


ChunkingServiceDependency = Annotated[
    KnowledgeChunkingService,
    Depends(get_chunking_service),
]


@router.post(
    "/{document_id}/versions/{version_id}/chunk-sets",
    response_model=KnowledgeChunkSetSummary,
    status_code=200,
)
async def create_chunk_set(
    document_id: str,
    version_id: str,
    payload: KnowledgeChunkingConfig,
    service: ChunkingServiceDependency,
) -> KnowledgeChunkSetSummary:
    """确保指定配置的批次存在；重复请求返回已有批次。"""

    try:
        # payload 使用已有 Schema：
        # {} 使用默认参数，缺少整个请求体则属于请求校验错误。
        return await service.create_chunk_set(
            document_id=document_id,
            version_id=version_id,
            config=payload,
        )
    except KnowledgeDocumentVersionNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document version not found",
        ) from error
    except KnowledgeChunkSourceNotReadyError as error:
        # 版本未解析成功，或者计算期间解析来源发生变化。
        # 调用方应先确认文档状态，不能直接绕过解析步骤。
        raise HTTPException(
            status_code=409,
            detail="Document version is not ready for chunking",
        ) from error
    except KnowledgeChunkingLimitError as error:
        # 参数本身可能合法，但与当前文本组合后产生过多片段。
        # 调用方需要调整配置，而不是无条件重试。
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except Exception as error:
        # 意外故障保留服务器堆栈，响应不暴露 SQL、路径等内部内容。
        logger.exception(
            "Knowledge chunk creation failed: document_id=%s version_id=%s",
            document_id,
            version_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Knowledge chunk creation failed",
        ) from error