"""HTTP endpoints for embedding profile configuration."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.knowledge.embedding_profiles import (
    EmbeddingProfileConflictError,
    EmbeddingProfileNotFoundError,
    KnowledgeEmbeddingProfileService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeEmbeddingProfileCreate,
    KnowledgeEmbeddingProfileResponse,
)


router = APIRouter(
    prefix="/knowledge-embedding-profiles",
    tags=["knowledge-embedding-profiles"],
)

SessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]


@router.get("", response_model=list[KnowledgeEmbeddingProfileResponse])
async def list_profiles(
    session: SessionDependency,
    provider_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeEmbeddingProfileResponse]:
    """查询配置列表，不调用模型，也不创建 Qdrant 集合。"""

    return await KnowledgeEmbeddingProfileService(session).list(
        provider_id=str(provider_id) if provider_id is not None else None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=KnowledgeEmbeddingProfileResponse,
    status_code=200,
)
async def create_profile(
    payload: KnowledgeEmbeddingProfileCreate,
    session: SessionDependency,
) -> KnowledgeEmbeddingProfileResponse:
    """确保配置存在；首次创建和重复复用统一返回 200。"""

    try:
        return await KnowledgeEmbeddingProfileService(session).create(payload)
    except EmbeddingProfileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except EmbeddingProfileConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/{profile_id}",
    response_model=KnowledgeEmbeddingProfileResponse,
)
async def get_profile(
    profile_id: UUID,
    session: SessionDependency,
) -> KnowledgeEmbeddingProfileResponse:
    """按 Profile ID 读取配置，UUID 格式错误由参数校验处理。"""

    try:
        return await KnowledgeEmbeddingProfileService(session).get(
            str(profile_id)
        )
    except EmbeddingProfileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error