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
    WeComBotChannelCreate,
    WeComBotChannelUpdate,
    WeComBotCredentialsUpdate,
    WeComChannelCreate,
    WeComChannelUpdate,
    WeComQrStartResponse,
    WeComQrStatusResponse,
    WeComSecretRotate,
)
from pawteam_api.channels.ingress import ChannelIngressError, ChannelIngressService
from pawteam_api.channels.service import (
    ChannelConfigurationError,
    ChannelConflictError,
    ChannelNotFoundError,
    ChannelService,
)
from pawteam_api.channels.wecom_bot import WeComBotError
from pawteam_api.channels.wecom_qr import WeComBotCredentials, WeComQrError

router = APIRouter(prefix="/channels", tags=["channels"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_channel_error(error: Exception) -> HTTPException:
    if isinstance(error, ChannelNotFoundError):
        return HTTPException(status_code=404, detail="Channel not found")
    if isinstance(
        error,
        (
            ChannelConfigurationError,
            ChannelConflictError,
            ChannelIngressError,
            WeComBotError,
            WeComQrError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Channel error")


@router.get("", response_model=list[ChannelResponse])
async def list_channels(
    request: Request, session: SessionDependency
) -> list[ChannelResponse]:
    channels = await ChannelService(session, request.app.state.secret_store).list()
    return [_with_runtime_status(request, channel) for channel in channels]


@router.post("/wecom-bot/qrcode", response_model=WeComQrStartResponse)
async def start_wecom_bot_qrcode(request: Request) -> WeComQrStartResponse:
    try:
        session_id, image, expires_in = await request.app.state.wecom_qr_service.start()
    except WeComQrError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return WeComQrStartResponse(
        auth_session_id=session_id,
        qrcode_image=image,
        expires_in=expires_in,
    )


@router.get(
    "/wecom-bot/qrcode/{auth_session_id}", response_model=WeComQrStatusResponse
)
async def poll_wecom_bot_qrcode(
    auth_session_id: str, request: Request
) -> WeComQrStatusResponse:
    try:
        qr_status, message = await request.app.state.wecom_qr_service.poll(
            auth_session_id
        )
    except WeComQrError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return WeComQrStatusResponse(status=qr_status, message=message)


@router.post(
    "/wecom-bot", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED
)
async def create_wecom_bot_channel(
    payload: WeComBotChannelCreate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        credentials = _bot_credentials(payload, request)
        response = await ChannelService(
            session, request.app.state.secret_store
        ).create_bot(payload, credentials)
        try:
            await request.app.state.wecom_bot_manager.start_channel(response.id)
        except WeComBotError:
            # The Channel and encrypted credentials are durable. Surface the
            # runtime error state so the user can retry without creating twice.
            pass
    except (
        ChannelConfigurationError,
        ChannelConflictError,
        WeComBotError,
        WeComQrError,
    ) as error:
        raise translate_channel_error(error) from error
    return _with_runtime_status(request, response)


@router.put("/wecom-bot/{channel_id}", response_model=ChannelResponse)
async def update_wecom_bot_channel(
    channel_id: str,
    payload: WeComBotChannelUpdate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        response = await ChannelService(
            session, request.app.state.secret_store
        ).update_bot(channel_id, payload)
    except (
        ChannelNotFoundError,
        ChannelConfigurationError,
        ChannelConflictError,
    ) as error:
        raise translate_channel_error(error) from error
    return _with_runtime_status(request, response)


@router.put("/wecom-bot/{channel_id}/credentials", response_model=ChannelResponse)
async def rotate_wecom_bot_credentials(
    channel_id: str,
    payload: WeComBotCredentialsUpdate,
    request: Request,
    session: SessionDependency,
) -> ChannelResponse:
    try:
        credentials = _bot_credentials(payload, request)
        response = await ChannelService(
            session, request.app.state.secret_store
        ).rotate_bot(
            channel_id,
            expected_version=payload.expected_version,
            credentials=credentials,
        )
        try:
            await request.app.state.wecom_bot_manager.start_channel(channel_id)
        except WeComBotError:
            pass
    except (
        ChannelNotFoundError,
        ChannelConfigurationError,
        ChannelConflictError,
        WeComBotError,
        WeComQrError,
    ) as error:
        raise translate_channel_error(error) from error
    return _with_runtime_status(request, response)


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
        response = await ChannelService(
            session, request.app.state.secret_store
        ).set_status(
            channel_id, payload
        )
    except (ChannelNotFoundError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error
    if response.kind == "wecom_bot":
        try:
            if response.status == "active":
                await request.app.state.wecom_bot_manager.start_channel(channel_id)
            else:
                await request.app.state.wecom_bot_manager.stop_channel(channel_id)
        except WeComBotError:
            pass
    return _with_runtime_status(request, response)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: str, request: Request, session: SessionDependency
) -> Response:
    try:
        service = ChannelService(session, request.app.state.secret_store)
        channel = await service.channel_model(channel_id)
        await service.delete(channel_id)
    except (ChannelNotFoundError, ChannelConflictError) as error:
        raise translate_channel_error(error) from error
    if channel.kind == "wecom_bot":
        await request.app.state.wecom_bot_manager.stop_channel(channel_id)
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


def _bot_credentials(
    payload: WeComBotChannelCreate | WeComBotCredentialsUpdate, request: Request
) -> WeComBotCredentials:
    if payload.auth_session_id is not None:
        return request.app.state.wecom_qr_service.consume(payload.auth_session_id)
    if payload.bot_id is None or payload.secret is None:
        raise WeComQrError("Bot ID and Secret are required")
    return WeComBotCredentials(bot_id=payload.bot_id.strip(), secret=payload.secret)


def _with_runtime_status(request: Request, channel: ChannelResponse) -> ChannelResponse:
    if channel.kind != "wecom_bot":
        return channel
    return channel.model_copy(
        update={
            "connection_status": request.app.state.wecom_bot_manager.status(channel.id)
        }
    )
