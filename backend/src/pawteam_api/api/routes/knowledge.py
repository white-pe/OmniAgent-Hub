"""Knowledge base management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.knowledge.bindings import (
    BindingConfigurationError,
    BindingConflictError,
    BindingNotFoundError,
    KnowledgeBaseBindingService,
)
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentKnowledgeBaseNotFoundError,
    KnowledgeDocumentService,
)
from pawteam_api.knowledge.service import (
    KnowledgeBaseConflictError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseBindingCreate,
    KnowledgeBaseBindingResponse,
    KnowledgeBaseBindingUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])
agent_binding_router = APIRouter(
    prefix="/agents",
    tags=["knowledge-bindings"],
)
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


@router.get(
    "/{knowledge_base_id}/documents",
    response_model=list[KnowledgeDocumentResponse],
)
async def list_knowledge_documents(
    knowledge_base_id: str,
    session: SessionDependency,
) -> list[KnowledgeDocumentResponse]:
    try:
        return await KnowledgeDocumentService(
            session
        ).list_for_knowledge_base(knowledge_base_id)
    except KnowledgeDocumentKnowledgeBaseNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        ) from error


@router.post(
    "/{knowledge_base_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_document(
    knowledge_base_id: str,
    payload: KnowledgeDocumentCreate,
    session: SessionDependency,
) -> KnowledgeDocumentResponse:
    try:
        return await KnowledgeDocumentService(session).create(
            knowledge_base_id,
            payload,
        )
    except KnowledgeDocumentKnowledgeBaseNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found",
        ) from error


def translate_binding_error(error: Exception) -> HTTPException:
    if isinstance(error, BindingNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, BindingConfigurationError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, BindingConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="Unexpected knowledge binding error",
    )


@agent_binding_router.get(
    "/{agent_id}/knowledge-bases",
    response_model=list[KnowledgeBaseBindingResponse],
)
async def list_agent_knowledge_bases(
    agent_id: str,
    session: SessionDependency,
) -> list[KnowledgeBaseBindingResponse]:
    try:
        return await KnowledgeBaseBindingService(session).list_for_agent(agent_id)
    except BindingConfigurationError as error:
        raise translate_binding_error(error) from error


@agent_binding_router.post(
    "/{agent_id}/knowledge-bases",
    response_model=KnowledgeBaseBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bind_knowledge_base(
    agent_id: str,
    payload: KnowledgeBaseBindingCreate,
    session: SessionDependency,
) -> KnowledgeBaseBindingResponse:
    try:
        return await KnowledgeBaseBindingService(session).create(
            agent_id,
            payload.knowledge_base_id,
        )
    except (
        BindingConfigurationError,
        BindingConflictError,
    ) as error:
        raise translate_binding_error(error) from error


@agent_binding_router.patch(
    "/{agent_id}/knowledge-bases/{knowledge_base_id}",
    response_model=KnowledgeBaseBindingResponse,
)
async def update_knowledge_base_binding(
    agent_id: str,
    knowledge_base_id: str,
    payload: KnowledgeBaseBindingUpdate,
    session: SessionDependency,
) -> KnowledgeBaseBindingResponse:
    try:
        return await KnowledgeBaseBindingService(session).set_enabled(
            agent_id,
            knowledge_base_id,
            payload,
        )
    except (
        BindingConfigurationError,
        BindingNotFoundError,
    ) as error:
        raise translate_binding_error(error) from error


@agent_binding_router.delete(
    "/{agent_id}/knowledge-bases/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_knowledge_base(
    agent_id: str,
    knowledge_base_id: str,
    session: SessionDependency,
) -> Response:
    try:
        await KnowledgeBaseBindingService(session).delete(
            agent_id,
            knowledge_base_id,
        )
    except (
        BindingConfigurationError,
        BindingNotFoundError,
    ) as error:
        raise translate_binding_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)