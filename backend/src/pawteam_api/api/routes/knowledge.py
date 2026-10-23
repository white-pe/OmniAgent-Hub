"""Knowledge base management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.knowledge.service import (
    KnowledgeBaseConflictError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_knowledge_base_error(error: Exception) -> HTTPException:
    if isinstance(error, KnowledgeBaseNotFoundError):
        return HTTPException(status_code=404, detail="Knowledge base not found")
    if isinstance(error, KnowledgeBaseConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="Unexpected knowledge base error",
    )


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    session: SessionDependency,
) -> list[KnowledgeBaseResponse]:
    return await KnowledgeBaseService(session).list()


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    session: SessionDependency,
) -> KnowledgeBaseResponse:
    try:
        return await KnowledgeBaseService(session).create(payload)
    except KnowledgeBaseConflictError as error:
        raise translate_knowledge_base_error(error) from error


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    knowledge_base_id: str,
    session: SessionDependency,
) -> KnowledgeBaseResponse:
    try:
        return await KnowledgeBaseService(session).get(knowledge_base_id)
    except KnowledgeBaseNotFoundError as error:
        raise translate_knowledge_base_error(error) from error


@router.put("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdate,
    session: SessionDependency,
) -> KnowledgeBaseResponse:
    try:
        return await KnowledgeBaseService(session).update(
            knowledge_base_id,
            payload,
        )
    except (
        KnowledgeBaseNotFoundError,
        KnowledgeBaseConflictError,
    ) as error:
        raise translate_knowledge_base_error(error) from error


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_base(
    knowledge_base_id: str,
    session: SessionDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    try:
        await KnowledgeBaseService(session).delete(
            knowledge_base_id,
            expected_version,
        )
    except (
        KnowledgeBaseNotFoundError,
        KnowledgeBaseConflictError,
    ) as error:
        raise translate_knowledge_base_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)