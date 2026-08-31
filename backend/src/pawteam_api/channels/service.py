"""Channel configuration and encrypted WeCom credential management."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.channel_schemas import (
    ChannelMessageResponse,
    ChannelResponse,
    ChannelStatusUpdate,
    WeComBotChannelCreate,
    WeComBotChannelUpdate,
    WeComChannelCreate,
    WeComChannelUpdate,
    WeComSecretRotate,
)
from pawteam_api.channels.wecom_qr import WeComBotCredentials
from pawteam_api.models import Agent, Channel, ChannelMessage
from pawteam_api.security.secret_store import (
    SecretNotFoundError,
    SecretStore,
    SecretStoreError,
)


class ChannelNotFoundError(LookupError):
    pass


class ChannelConflictError(ValueError):
    pass


class ChannelConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class WeComSecrets:
    token: str
    encoding_aes_key: str
    corp_secret: str


@dataclass(frozen=True)
class WeComBotSecrets:
    secret: str


class ChannelService:
    def __init__(self, session: AsyncSession, secret_store: SecretStore) -> None:
        self.session = session
        self.secret_store = secret_store

    async def list(self) -> list[ChannelResponse]:
        rows = (
            await self.session.execute(
                select(Channel, Agent.name)
                .join(Agent, Agent.id == Channel.agent_id)
                .order_by(Channel.created_at, Channel.name)
            )
        ).all()
        return [self._response(channel, agent_name) for channel, agent_name in rows]

    async def get(self, channel_id: str) -> ChannelResponse:
        channel, agent_name = await self._row(channel_id)
        return self._response(channel, agent_name)

    async def create(self, payload: WeComChannelCreate) -> ChannelResponse:
        agent = await self._active_agent(payload.agent_id)
        channel_id = str(uuid4())
        secret_ref = f"channel_{channel_id}"
        secrets = WeComSecrets(
            token=payload.token,
            encoding_aes_key=payload.encoding_aes_key,
            corp_secret=payload.corp_secret,
        )
        self.secret_store.set(secret_ref, json.dumps(asdict(secrets)))
        channel = Channel(
            id=channel_id,
            name=payload.name.strip(),
            kind="wecom",
            agent_id=agent.id,
            secret_ref=secret_ref,
            status="active",
            config_json={
                "corp_id": payload.corp_id,
                "wecom_agent_id": payload.wecom_agent_id,
            },
            version=1,
        )
        self.session.add(channel)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self.secret_store.delete(secret_ref)
            raise ChannelConflictError("Channel name already exists") from exc
        except Exception:
            await self.session.rollback()
            self.secret_store.delete(secret_ref)
            raise
        await self.session.refresh(channel)
        return self._response(channel, agent.name)

    async def create_bot(
        self,
        payload: WeComBotChannelCreate,
        credentials: WeComBotCredentials,
    ) -> ChannelResponse:
        agent = await self._active_agent(payload.agent_id)
        channel_id = str(uuid4())
        secret_ref = f"channel_{channel_id}"
        self.secret_store.set(
            secret_ref,
            json.dumps(asdict(WeComBotSecrets(secret=credentials.secret))),
        )
        channel = Channel(
            id=channel_id,
            name=payload.name.strip(),
            kind="wecom_bot",
            agent_id=agent.id,
            secret_ref=secret_ref,
            status="active",
            config_json={"bot_id": credentials.bot_id},
            version=1,
        )
        self.session.add(channel)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self.secret_store.delete(secret_ref)
            raise ChannelConflictError("Channel name already exists") from exc
        except Exception:
            await self.session.rollback()
            self.secret_store.delete(secret_ref)
            raise
        await self.session.refresh(channel)
        return self._response(channel, agent.name)

    async def update(
        self, channel_id: str, payload: WeComChannelUpdate
    ) -> ChannelResponse:
        channel, _ = await self._row(channel_id)
        self._require_kind(channel, "wecom")
        self._check_version(channel, payload.expected_version)
        agent = await self._active_agent(payload.agent_id)
        channel.name = payload.name.strip()
        channel.agent_id = agent.id
        channel.config_json = {
            "corp_id": payload.corp_id.strip(),
            "wecom_agent_id": payload.wecom_agent_id,
        }
        channel.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ChannelConflictError("Channel name already exists") from exc
        await self.session.refresh(channel)
        return self._response(channel, agent.name)

    async def update_bot(
        self, channel_id: str, payload: WeComBotChannelUpdate
    ) -> ChannelResponse:
        channel, _ = await self._row(channel_id)
        self._require_kind(channel, "wecom_bot")
        self._check_version(channel, payload.expected_version)
        agent = await self._active_agent(payload.agent_id)
        channel.name = payload.name.strip()
        channel.agent_id = agent.id
        channel.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ChannelConflictError("Channel name already exists") from exc
        await self.session.refresh(channel)
        return self._response(channel, agent.name)

    async def rotate_bot(
        self,
        channel_id: str,
        *,
        expected_version: int,
        credentials: WeComBotCredentials,
    ) -> ChannelResponse:
        channel, agent_name = await self._row(channel_id)
        self._require_kind(channel, "wecom_bot")
        self._check_version(channel, expected_version)
        previous = self.secret_store.get(channel.secret_ref)
        self.secret_store.set(
            channel.secret_ref,
            json.dumps(asdict(WeComBotSecrets(secret=credentials.secret))),
        )
        channel.config_json = {"bot_id": credentials.bot_id}
        channel.version += 1
        try:
            await self.session.commit()
        except Exception:
            self.secret_store.set(channel.secret_ref, previous)
            raise
        await self.session.refresh(channel)
        return self._response(channel, agent_name)

    async def rotate(
        self, channel_id: str, payload: WeComSecretRotate
    ) -> ChannelResponse:
        channel, agent_name = await self._row(channel_id)
        self._require_kind(channel, "wecom")
        self._check_version(channel, payload.expected_version)
        previous = self.secret_store.get(channel.secret_ref)
        replacement = WeComSecrets(
            token=payload.token,
            encoding_aes_key=payload.encoding_aes_key,
            corp_secret=payload.corp_secret,
        )
        self.secret_store.set(channel.secret_ref, json.dumps(asdict(replacement)))
        channel.version += 1
        try:
            await self.session.commit()
        except Exception:
            self.secret_store.set(channel.secret_ref, previous)
            raise
        await self.session.refresh(channel)
        return self._response(channel, agent_name)

    async def set_status(
        self, channel_id: str, payload: ChannelStatusUpdate
    ) -> ChannelResponse:
        channel, agent_name = await self._row(channel_id)
        self._check_version(channel, payload.expected_version)
        channel.status = payload.status
        channel.version += 1
        await self.session.commit()
        await self.session.refresh(channel)
        return self._response(channel, agent_name)

    async def delete(self, channel_id: str) -> None:
        channel, _ = await self._row(channel_id)
        has_history = await self.session.scalar(
            select(ChannelMessage.id)
            .where(ChannelMessage.channel_id == channel.id)
            .limit(1)
        )
        if has_history is not None:
            raise ChannelConflictError(
                "Channel has message history; disable it instead of deleting it"
            )
        reference = channel.secret_ref
        await self.session.delete(channel)
        await self.session.commit()
        self.secret_store.delete(reference)

    async def messages(
        self, channel_id: str, *, limit: int = 100
    ) -> list[ChannelMessageResponse]:
        await self._row(channel_id)
        messages = (
            await self.session.scalars(
                select(ChannelMessage)
                .where(ChannelMessage.channel_id == channel_id)
                .order_by(ChannelMessage.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [self.message_response(message) for message in messages]

    async def channel_model(self, channel_id: str, *, active: bool = False) -> Channel:
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            raise ChannelNotFoundError(channel_id)
        if active and channel.status != "active":
            raise ChannelConfigurationError("Channel is disabled")
        return channel

    def secrets(self, channel: Channel) -> WeComSecrets:
        self._require_kind(channel, "wecom")
        try:
            raw = json.loads(self.secret_store.get(channel.secret_ref))
            return WeComSecrets(
                token=str(raw["token"]),
                encoding_aes_key=str(raw["encoding_aes_key"]),
                corp_secret=str(raw["corp_secret"]),
            )
        except (
            SecretNotFoundError,
            SecretStoreError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise ChannelConfigurationError(
                "Channel credentials are missing or invalid"
            ) from exc

    def bot_secrets(self, channel: Channel) -> WeComBotSecrets:
        self._require_kind(channel, "wecom_bot")
        try:
            raw = json.loads(self.secret_store.get(channel.secret_ref))
            return WeComBotSecrets(secret=str(raw["secret"]))
        except (
            SecretNotFoundError,
            SecretStoreError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise ChannelConfigurationError(
                "Channel bot credentials are missing or invalid"
            ) from exc

    async def _row(self, channel_id: str) -> tuple[Channel, str]:
        row = (
            await self.session.execute(
                select(Channel, Agent.name)
                .join(Agent, Agent.id == Channel.agent_id)
                .where(Channel.id == channel_id)
            )
        ).one_or_none()
        if row is None:
            raise ChannelNotFoundError(channel_id)
        return row

    async def _active_agent(self, agent_id: str) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise ChannelConfigurationError("Selected Agent does not exist")
        if agent.status != "active":
            raise ChannelConfigurationError("Selected Agent is disabled")
        return agent

    @staticmethod
    def _check_version(channel: Channel, expected: int) -> None:
        if channel.version != expected:
            raise ChannelConflictError(
                "Channel was changed by another request; "
                f"current version is {channel.version}"
            )

    @staticmethod
    def _require_kind(channel: Channel, kind: str) -> None:
        if channel.kind != kind:
            raise ChannelConfigurationError(
                f"Channel mode is {channel.kind}, expected {kind}"
            )

    def _response(self, channel: Channel, agent_name: str) -> ChannelResponse:
        is_bot = channel.kind == "wecom_bot"
        bot_id = str(channel.config_json.get("bot_id", ""))
        return ChannelResponse(
            id=channel.id,
            name=channel.name,
            kind="wecom_bot" if is_bot else "wecom",
            agent_id=channel.agent_id,
            agent_name=agent_name,
            status=channel.status,
            corp_id=(
                None if is_bot else str(channel.config_json.get("corp_id", ""))
            ),
            wecom_agent_id=(
                None
                if is_bot
                else int(channel.config_json.get("wecom_agent_id", 0))
            ),
            bot_id_masked=self._mask(bot_id) if is_bot else None,
            callback_path=(
                None
                if is_bot
                else f"/api/channel-webhooks/wecom/{channel.id}"
            ),
            has_secrets=self.secret_store.exists(channel.secret_ref),
            version=channel.version,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )

    @staticmethod
    def _mask(value: str) -> str:
        if len(value) <= 10:
            return f"{value[:3]}***"
        return f"{value[:7]}***{value[-4:]}"

    @staticmethod
    def message_response(message: ChannelMessage) -> ChannelMessageResponse:
        return ChannelMessageResponse(
            id=message.id,
            channel_id=message.channel_id,
            external_conversation_id=message.external_conversation_id,
            external_user_id=message.external_user_id,
            external_message_id=message.external_message_id,
            direction=message.direction,
            content=message.content,
            status=message.status,
            chat_session_id=message.chat_session_id,
            run_id=message.run_id,
            attempts=message.attempts,
            error_message=message.error_message,
            delivered_at=message.delivered_at,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )
