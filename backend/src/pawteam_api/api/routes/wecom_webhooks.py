"""Public WeCom callback endpoints for URL verification and messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.channels.ingress import ChannelIngressError, ChannelIngressService
from pawteam_api.channels.service import (
    ChannelConfigurationError,
    ChannelNotFoundError,
    ChannelService,
)
from pawteam_api.channels.wecom_crypto import WeComCrypto, WeComCryptoError
from pawteam_api.channels.wecom_xml import (
    WeComXmlError,
    encrypted_value,
    parse_plain_message,
)
from pawteam_api.models import Channel

router = APIRouter(prefix="/channel-webhooks/wecom", tags=["channel-webhooks"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def _check_timestamp(timestamp: str, tolerance: int) -> None:
    try:
        received = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid callback timestamp"
        ) from exc
    now = int(datetime.now(UTC).timestamp())
    if abs(now - received) > tolerance:
        raise HTTPException(status_code=401, detail="Callback timestamp expired")


async def _boundary(
    channel_id: str,
    request: Request,
    session: AsyncSession,
) -> tuple[Channel, WeComCrypto]:
    service = ChannelService(session, request.app.state.secret_store)
    try:
        channel = await service.channel_model(channel_id, active=True)
        secrets = service.secrets(channel)
        crypto = WeComCrypto(
            secrets.token,
            secrets.encoding_aes_key,
            str(channel.config_json["corp_id"]),
        )
        return channel, crypto
    except ChannelNotFoundError as error:
        raise HTTPException(status_code=404, detail="Channel not found") from error
    except (ChannelConfigurationError, WeComCryptoError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{channel_id}", response_class=PlainTextResponse)
async def verify_callback(
    channel_id: str,
    request: Request,
    session: SessionDependency,
    msg_signature: str = Query(min_length=1),
    timestamp: str = Query(min_length=1),
    nonce: str = Query(min_length=1),
    echostr: str = Query(min_length=1),
) -> PlainTextResponse:
    _check_timestamp(
        timestamp, request.app.state.settings.channel_signature_tolerance_seconds
    )
    _, crypto = await _boundary(channel_id, request, session)
    try:
        plain = crypto.verify_and_decrypt(
            signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            encrypted=echostr,
        )
        return PlainTextResponse(plain.decode("utf-8"))
    except (WeComCryptoError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@router.post("/{channel_id}", response_class=PlainTextResponse)
async def receive_callback(
    channel_id: str,
    request: Request,
    session: SessionDependency,
    msg_signature: str = Query(min_length=1),
    timestamp: str = Query(min_length=1),
    nonce: str = Query(min_length=1),
) -> PlainTextResponse:
    _check_timestamp(
        timestamp, request.app.state.settings.channel_signature_tolerance_seconds
    )
    channel, crypto = await _boundary(channel_id, request, session)
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Callback body is too large")
    try:
        encrypted = encrypted_value(body)
        plain = crypto.verify_and_decrypt(
            signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            encrypted=encrypted,
        )
        inbound = parse_plain_message(plain)
    except (WeComCryptoError, WeComXmlError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    if inbound.message_type != "text" or not inbound.content:
        return PlainTextResponse("success")
    try:
        result = await ChannelIngressService(session).receive_text(
            channel=channel,
            external_conversation_id=inbound.user_id,
            external_user_id=inbound.user_id,
            external_message_id=inbound.message_id,
            content=inbound.content,
        )
    except ChannelIngressError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if result.run_id is not None and not result.duplicate:
        request.app.state.run_manager.start(result.run_id)
    if result.outbound_message_id is not None:
        request.app.state.channel_dispatcher.dispatch(result.outbound_message_id)
    return PlainTextResponse("success")
