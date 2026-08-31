"""Team configuration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.team_schemas import TeamCreate, TeamResponse, TeamUpdate
from pawteam_api.teams.service import (
    TeamConfigurationError,
    TeamConflictError,
    TeamNotFoundError,
    TeamService,
)

router = APIRouter(prefix="/teams", tags=["teams"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_team_error(error: Exception) -> HTTPException:
    if isinstance(error, TeamNotFoundError):
        return HTTPException(status_code=404, detail="Team not found")
    if isinstance(error, (TeamConfigurationError, TeamConflictError)):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Team error")


@router.get("", response_model=list[TeamResponse])
async def list_teams(session: SessionDependency) -> list[TeamResponse]:
    return await TeamService(session).list()


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate, session: SessionDependency) -> TeamResponse:
    try:
        return await TeamService(session).create(payload)
    except (TeamConfigurationError, TeamConflictError) as error:
        raise translate_team_error(error) from error


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str, payload: TeamUpdate, session: SessionDependency
) -> TeamResponse:
    try:
        return await TeamService(session).update(team_id, payload)
    except (
        TeamNotFoundError,
        TeamConfigurationError,
        TeamConflictError,
    ) as error:
        raise translate_team_error(error) from error


@router.post("/{team_id}/toggle", response_model=TeamResponse)
async def toggle_team(team_id: str, session: SessionDependency) -> TeamResponse:
    try:
        return await TeamService(session).toggle(team_id)
    except TeamNotFoundError as error:
        raise translate_team_error(error) from error


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: str, session: SessionDependency) -> Response:
    try:
        await TeamService(session).delete(team_id)
    except (TeamNotFoundError, TeamConflictError) as error:
        raise translate_team_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
