"""Agent Skill CRUD backed by isolated Workspace SKILL.md files."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.skill_schemas import SkillCreate, SkillResponse, SkillUpdate
from pawteam_api.skills.service import (
    SkillConfigurationError,
    SkillConflictError,
    SkillNotFoundError,
    SkillService,
)
from pawteam_api.workspaces.store import WorkspaceError

router = APIRouter(prefix="/agents", tags=["skills"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def skill_service(request: Request, session: AsyncSession) -> SkillService:
    return SkillService(session, request.app.state.workspace_store)


def translate_skill_error(error: Exception) -> HTTPException:
    if isinstance(error, SkillNotFoundError):
        return HTTPException(status_code=404, detail="Skill not found")
    if isinstance(error, SkillConfigurationError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, (SkillConflictError, WorkspaceError)):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Skill error")


@router.get("/{agent_id}/skills", response_model=list[SkillResponse])
async def list_skills(
    agent_id: str,
    request: Request,
    session: SessionDependency,
) -> list[SkillResponse]:
    try:
        return await skill_service(request, session).list(agent_id)
    except (SkillConfigurationError, WorkspaceError) as error:
        raise translate_skill_error(error) from error


@router.post(
    "/{agent_id}/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_skill(
    agent_id: str,
    payload: SkillCreate,
    request: Request,
    session: SessionDependency,
) -> SkillResponse:
    try:
        return await skill_service(request, session).create(agent_id, payload)
    except (
        SkillConfigurationError,
        SkillConflictError,
        WorkspaceError,
    ) as error:
        raise translate_skill_error(error) from error


@router.put("/{agent_id}/skills/{skill_name}", response_model=SkillResponse)
async def update_skill(
    agent_id: str,
    skill_name: str,
    payload: SkillUpdate,
    request: Request,
    session: SessionDependency,
) -> SkillResponse:
    try:
        return await skill_service(request, session).update(
            agent_id, skill_name, payload
        )
    except (
        SkillConfigurationError,
        SkillNotFoundError,
        SkillConflictError,
        WorkspaceError,
    ) as error:
        raise translate_skill_error(error) from error


@router.post("/{agent_id}/skills/{skill_name}/toggle", response_model=SkillResponse)
async def toggle_skill(
    agent_id: str,
    skill_name: str,
    request: Request,
    session: SessionDependency,
) -> SkillResponse:
    try:
        return await skill_service(request, session).toggle(agent_id, skill_name)
    except (
        SkillConfigurationError,
        SkillNotFoundError,
        WorkspaceError,
    ) as error:
        raise translate_skill_error(error) from error


@router.delete(
    "/{agent_id}/skills/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill(
    agent_id: str,
    skill_name: str,
    request: Request,
    session: SessionDependency,
) -> Response:
    try:
        await skill_service(request, session).delete(agent_id, skill_name)
    except (
        SkillConfigurationError,
        SkillNotFoundError,
        WorkspaceError,
    ) as error:
        raise translate_skill_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
