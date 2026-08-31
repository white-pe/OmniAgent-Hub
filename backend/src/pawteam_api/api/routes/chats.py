"""Durable console chat creation, history, and Run submission."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.chat_schemas import (
    ChatCreate,
    ChatDetailResponse,
    ChatSessionResponse,
    RunCreate,
    RunResponse,
)
from pawteam_api.runtime.service import (
    ChatConfigurationError,
    ChatConflictError,
    ChatNotFoundError,
    ChatService,
    RunCommandService,
    RunConflictError,
)

router = APIRouter(prefix="/chats", tags=["chats"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_chat_error(error: Exception) -> HTTPException:
    if isinstance(error, ChatNotFoundError):
        return HTTPException(status_code=404, detail="Chat not found")
    if isinstance(
        error,
        (
            ChatConflictError,
            ChatConfigurationError,
            RunConflictError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Chat error")


@router.post(
    "",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat(
    payload: ChatCreate,
    session: SessionDependency,
) -> ChatSessionResponse:
    try:
        return await ChatService(session).create(payload)
    except ChatConfigurationError as error:
        raise translate_chat_error(error) from error


@router.get("", response_model=list[ChatSessionResponse])
async def list_chats(
    session: SessionDependency,
    agent_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[ChatSessionResponse]:
    return await ChatService(session).list(agent_id)


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: str,
    session: SessionDependency,
) -> ChatDetailResponse:
    try:
        return await ChatService(session).get(chat_id)
    except ChatNotFoundError as error:
        raise translate_chat_error(error) from error


@router.post(
    "/{chat_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    chat_id: str,
    payload: RunCreate,
    request: Request,
    session: SessionDependency,
) -> RunResponse:
    try:
        run = await RunCommandService(session).create(chat_id, payload)
    except (
        ChatNotFoundError,
        ChatConflictError,
        ChatConfigurationError,
        RunConflictError,
    ) as error:
        raise translate_chat_error(error) from error
    request.app.state.run_manager.start(run.id)
    return run
