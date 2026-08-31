"""Per-Agent Tool discovery and explicit enablement API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.tool_schemas import ToolAssignmentResponse
from pawteam_api.tools.service import (
    ToolAssignmentService,
    ToolConfigurationError,
    ToolNotFoundError,
)

router = APIRouter(prefix="/agents", tags=["tools"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def tool_service(request: Request, session: AsyncSession) -> ToolAssignmentService:
    return ToolAssignmentService(session, request.app.state.tool_registry)


@router.get("/{agent_id}/tools", response_model=list[ToolAssignmentResponse])
async def list_tools(
    agent_id: str,
    request: Request,
    session: SessionDependency,
) -> list[ToolAssignmentResponse]:
    try:
        return await tool_service(request, session).list(agent_id)
    except ToolConfigurationError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/{agent_id}/tools/{tool_name}/toggle",
    response_model=ToolAssignmentResponse,
)
async def toggle_tool(
    agent_id: str,
    tool_name: str,
    request: Request,
    session: SessionDependency,
) -> ToolAssignmentResponse:
    try:
        return await tool_service(request, session).toggle(agent_id, tool_name)
    except (ToolConfigurationError, ToolNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
