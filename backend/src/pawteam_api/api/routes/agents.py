"""Agent CRUD and Workspace file endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.agent_schemas import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    WorkspaceFileResponse,
    WorkspaceFileUpdate,
)
from pawteam_api.agents.service import (
    AgentConfigurationError,
    AgentConflictError,
    AgentNotFoundError,
    AgentService,
)
from pawteam_api.api.dependencies import get_database_session
from pawteam_api.api.routes.blueprints import (
    blueprint_service,
    translate_blueprint_error,
)
from pawteam_api.blueprint_schemas import BlueprintApplyRequest
from pawteam_api.blueprints.service import (
    BlueprintConflictError,
    BlueprintNotFoundError,
)
from pawteam_api.workspaces.store import (
    WorkspaceError,
    WorkspaceFileNotAllowedError,
)

router = APIRouter(prefix="/agents", tags=["agents"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def agent_service(request: Request, session: AsyncSession) -> AgentService:
    return AgentService(session, request.app.state.workspace_store)


def translate_agent_error(error: Exception) -> HTTPException:
    if isinstance(error, AgentNotFoundError):
        return HTTPException(status_code=404, detail="Agent not found")
    if isinstance(error, WorkspaceFileNotAllowedError):
        return HTTPException(status_code=404, detail="Workspace file is not allowed")
    if isinstance(error, AgentConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, AgentConfigurationError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, WorkspaceError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Agent error")


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    request: Request, session: SessionDependency
) -> list[AgentResponse]:
    return await agent_service(request, session).list()


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate, request: Request, session: SessionDependency
) -> AgentResponse:
    try:
        return await agent_service(request, session).create(payload)
    except (AgentConflictError, AgentConfigurationError, WorkspaceError) as error:
        raise translate_agent_error(error) from error


@router.post("/from-blueprint", response_model=AgentResponse)
async def create_agent_from_blueprint(
    payload: BlueprintApplyRequest,
    request: Request,
    session: SessionDependency,
) -> AgentResponse:
    try:
        return await blueprint_service(request, session).apply(
            draft_id=payload.draft_id,
            blueprint=payload.blueprint,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
        )
    except (
        BlueprintNotFoundError,
        BlueprintConflictError,
        AgentConflictError,
        AgentConfigurationError,
        WorkspaceError,
    ) as error:
        if isinstance(
            error,
            (AgentConflictError, AgentConfigurationError, WorkspaceError),
        ):
            raise translate_agent_error(error) from error
        raise translate_blueprint_error(error) from error


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str, request: Request, session: SessionDependency
) -> AgentResponse:
    try:
        return await agent_service(request, session).get(agent_id)
    except AgentNotFoundError as error:
        raise translate_agent_error(error) from error


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    request: Request,
    session: SessionDependency,
) -> AgentResponse:
    try:
        return await agent_service(request, session).update(agent_id, payload)
    except (
        AgentNotFoundError,
        AgentConflictError,
        AgentConfigurationError,
    ) as error:
        raise translate_agent_error(error) from error


@router.post("/{agent_id}/toggle", response_model=AgentResponse)
async def toggle_agent(
    agent_id: str, request: Request, session: SessionDependency
) -> AgentResponse:
    try:
        return await agent_service(request, session).toggle(agent_id)
    except AgentNotFoundError as error:
        raise translate_agent_error(error) from error


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str, request: Request, session: SessionDependency
) -> Response:
    try:
        await agent_service(request, session).delete(agent_id)
    except (AgentNotFoundError, AgentConflictError, WorkspaceError) as error:
        raise translate_agent_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/files/{filename}", response_model=WorkspaceFileResponse)
async def get_workspace_file(
    agent_id: str,
    filename: str,
    request: Request,
    session: SessionDependency,
) -> WorkspaceFileResponse:
    try:
        return await agent_service(request, session).get_file(agent_id, filename)
    except (
        AgentNotFoundError,
        WorkspaceFileNotAllowedError,
        WorkspaceError,
    ) as error:
        raise translate_agent_error(error) from error


@router.put("/{agent_id}/files/{filename}", response_model=WorkspaceFileResponse)
async def update_workspace_file(
    agent_id: str,
    filename: str,
    payload: WorkspaceFileUpdate,
    request: Request,
    session: SessionDependency,
) -> WorkspaceFileResponse:
    try:
        return await agent_service(request, session).update_file(
            agent_id, filename, payload
        )
    except (
        AgentNotFoundError,
        AgentConflictError,
        WorkspaceFileNotAllowedError,
        WorkspaceError,
    ) as error:
        raise translate_agent_error(error) from error
