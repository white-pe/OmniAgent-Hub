"""Channel configuration, inspection, and local ingress debugging."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.channel_schemas import (
    ChannelIngressResponse,
    ChannelMessageResponse,
    ChannelResponse,
    ChannelStatusUpdate,
    DebugInboundCreate,
    WeComChannelCreate,
    WeComChannelUpdate,
    WeComSecretRotate,
)
from pawteam_api.channels.ingress import ChannelIngressError, ChannelIngressService
from pawteam_api.channels.service import (
    ChannelConfigurationError,
    ChannelConflictError,
    ChannelNotFoundError,
    ChannelService,
)

router = APIRouter(prefix="/channels", tags=["channels"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_channel_error(error: Exception) -> HTTPException:
    if isinstance(error, ChannelNotFoundError):
        return HTTPException(status_code=404, detail="Channel not found")
    if isinstance(
        error,
        (ChannelConfigurationError, ChannelConflictError, ChannelIngressError),
    ):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Channel error")


@router.get("", response_model=list[ChannelResponse])
async def list_channels(
    request: Request, session: SessionDependency
) -> list[ChannelResponse]:
    return await ChannelService(session, request.app.state.secret_store).list()


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: WeComChannelCreate, request: Request, session: SessionDependency
) -> ChannelResponse:
    try:
        return await ChannelService(session, request.app.state.secret_store).create(
            payload
        )
    except (ChannelConfigurationError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    payload: WeComChannelUpdate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        response = await ChannelService(session, request.app.state.secret_store).update(
            channel_id, payload
        )
    except (
        ChannelNotFoundError,
        ChannelConfigurationError,
        ChannelConflictError,
    ) as error:
        raise translate_channel_error(error) from error
    request.app.state.channel_dispatcher.invalidate_channel(channel_id)
    return response


@router.put("/{channel_id}/secrets", response_model=ChannelResponse)
async def rotate_channel_secrets(
    channel_id: str,
    payload: WeComSecretRotate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        response = await ChannelService(session, request.app.state.secret_store).rotate(
            channel_id, payload
        )
    except (ChannelNotFoundError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error
    request.app.state.channel_dispatcher.invalidate_channel(channel_id)
    return response


@router.put("/{channel_id}/status", response_model=ChannelResponse)
async def set_channel_status(
    channel_id: str,
    payload: ChannelStatusUpdate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        return await ChannelService(session, request.app.state.secret_store).set_status(
            channel_id, payload
        )
    except (ChannelNotFoundError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: str, request: Request, session: SessionDependency
) -> Response:
    try:
        await ChannelService(session, request.app.state.secret_store).delete(channel_id)
    except (ChannelNotFoundError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{channel_id}/messages", response_model=list[ChannelMessageResponse])
async def list_channel_messages(
    channel_id: str,
    request: Request,
    session: SessionDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ChannelMessageResponse]:
    try:
        return await ChannelService(session, request.app.state.secret_store).messages(
            channel_id, limit=limit
        )
    except ChannelNotFoundError as error:
        raise translate_channel_error(error) from error


@router.post(
    "/{channel_id}/debug-inbound",
    response_model=ChannelIngressResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def debug_inbound(
    channel_id: str,
    payload: DebugInboundCreate,
    request: Request,
    session: SessionDependency,
) -> ChannelIngressResponse:
    service = ChannelService(session, request.app.state.secret_store)
    try:
        channel = await service.channel_model(channel_id, active=True)
        conversation_id = payload.external_conversation_id or payload.external_user_id
        message_id = payload.external_message_id or f"debug:{uuid4()}"
        result = await ChannelIngressService(session).receive_text(
            channel=channel,
            external_conversation_id=conversation_id,
            external_user_id=payload.external_user_id,
            external_message_id=message_id,
            content=payload.content,
        )
    except (
        ChannelNotFoundError,
        ChannelConfigurationError,
        ChannelIngressError,
    ) as error:
        raise translate_channel_error(error) from error
    if result.run_id is not None and not result.duplicate:
        request.app.state.run_manager.start(result.run_id)
    if result.outbound_message_id is not None:
        request.app.state.channel_dispatcher.dispatch(result.outbound_message_id)
    return ChannelIngressResponse(**result.__dict__)


@router.post("/messages/{message_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_channel_message(message_id: str, request: Request) -> dict[str, str]:
    try:
        await request.app.state.channel_dispatcher.retry(message_id)
    except LookupError as error:
        raise HTTPException(
            status_code=404, detail="Outbound message not found"
        ) from error
    return {"status": "accepted"}
