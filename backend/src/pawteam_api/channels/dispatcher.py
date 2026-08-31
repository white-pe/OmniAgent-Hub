"""Durable outbound delivery with bounded retries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.channels.service import WeComSecrets
from pawteam_api.channels.wecom_client import WeComApiClient, WeComRequestError
from pawteam_api.config import Settings
from pawteam_api.models import Channel, ChannelMessage
from pawteam_api.security.secret_store import SecretStore, SecretStoreError

WeComClientFactory = Callable[[float], WeComApiClient]


class ChannelDispatcher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        secret_store: SecretStore,
        client_factory: WeComClientFactory = WeComApiClient,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.secret_store = secret_store
        self.client_factory = client_factory
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.token_cache: dict[str, tuple[str, datetime]] = {}

    def dispatch(self, message_id: str) -> None:
        if message_id in self.tasks:
            return
        task = asyncio.create_task(
            self._deliver_with_retry(message_id), name=f"channel-delivery-{message_id}"
        )
        self.tasks[message_id] = task
        task.add_done_callback(
            lambda completed, current_id=message_id: self.tasks.pop(current_id, None)
        )

    async def recover_pending(self) -> None:
        try:
            async with self.session_factory() as session:
                ids = (
                    await session.scalars(
                        select(ChannelMessage.id)
                        .where(
                            ChannelMessage.direction == "outbound",
                            ChannelMessage.status.in_(
                                ("pending", "retrying", "delivering")
                            ),
                        )
                        .order_by(ChannelMessage.created_at)
                        .limit(self.settings.channel_outbox_batch_size)
                    )
                ).all()
        except OperationalError as error:
            if "no such table: channel_messages" not in str(error):
                raise
            return
        for message_id in ids:
            self.dispatch(message_id)

    async def shutdown(self) -> None:
        running = [task for task in self.tasks.values() if not task.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    async def retry(self, message_id: str) -> None:
        async with self.session_factory() as session:
            message = await session.get(ChannelMessage, message_id)
            if message is None or message.direction != "outbound":
                raise LookupError(message_id)
            message.status = "pending"
            message.attempts = 0
            message.error_message = None
            message.lease_until = None
            await session.commit()
        self.dispatch(message_id)

    def invalidate_channel(self, channel_id: str) -> None:
        self.token_cache.pop(channel_id, None)

    async def _deliver_with_retry(self, message_id: str) -> None:
        while True:
            channel_id: str | None = None
            try:
                claimed = await self._claim(message_id)
                if claimed is None:
                    return
                channel, message = claimed
                channel_id = channel.id
                await self._send(channel, message)
                await self._mark_delivered(message_id)
                return
            except asyncio.CancelledError:
                raise
            except (WeComRequestError, SecretStoreError, ValueError, KeyError) as exc:
                if channel_id is not None:
                    self.token_cache.pop(channel_id, None)
                attempts = await self._mark_failed_attempt(message_id, str(exc))
                if attempts >= self.settings.channel_outbox_max_attempts:
                    return
                await asyncio.sleep(min(2 ** (attempts - 1), 30))

    async def _claim(self, message_id: str) -> tuple[Channel, ChannelMessage] | None:
        async with self.session_factory() as session:
            message = await session.get(ChannelMessage, message_id)
            if message is None or message.direction != "outbound":
                return None
            if message.status == "delivered" or message.attempts >= (
                self.settings.channel_outbox_max_attempts
            ):
                return None
            channel = await session.get(Channel, message.channel_id)
            if channel is None or channel.status != "active":
                message.status = "failed"
                message.error_message = "Channel is missing or disabled"
                await session.commit()
                return None
            message.status = "delivering"
            message.attempts += 1
            message.lease_until = self._now() + timedelta(
                seconds=self.settings.channel_outbox_lease_seconds
            )
            await session.commit()
            return channel, message

    async def _send(self, channel: Channel, message: ChannelMessage) -> None:
        raw = json.loads(self.secret_store.get(channel.secret_ref))
        secrets = WeComSecrets(
            token=str(raw["token"]),
            encoding_aes_key=str(raw["encoding_aes_key"]),
            corp_secret=str(raw["corp_secret"]),
        )
        corp_id = str(channel.config_json["corp_id"])
        agent_id = int(channel.config_json["wecom_agent_id"])
        token = await self._token(channel.id, corp_id, secrets.corp_secret)
        client = self.client_factory(self.settings.channel_delivery_timeout_seconds)
        chunks = self._text_chunks(message.content)
        for index, chunk in enumerate(chunks, start=1):
            content = f"({index}/{len(chunks)})\n{chunk}" if len(chunks) > 1 else chunk
            await client.send_text(
                access_token=token,
                user_id=message.external_user_id,
                agent_id=agent_id,
                content=content,
            )

    async def _token(self, channel_id: str, corp_id: str, secret: str) -> str:
        cached = self.token_cache.get(channel_id)
        now = self._now()
        if cached is not None and cached[1] > now:
            return cached[0]
        result = await self.client_factory(
            self.settings.channel_delivery_timeout_seconds
        ).access_token(corp_id, secret)
        expires_at = now + timedelta(seconds=max(60, result.expires_in - 300))
        self.token_cache[channel_id] = (result.value, expires_at)
        return result.value

    async def _mark_delivered(self, message_id: str) -> None:
        async with self.session_factory() as session:
            message = await session.get(ChannelMessage, message_id)
            if message is None:
                return
            message.status = "delivered"
            message.error_message = None
            message.lease_until = None
            message.delivered_at = self._now()
            await session.commit()

    async def _mark_failed_attempt(self, message_id: str, error: str) -> int:
        async with self.session_factory() as session:
            message = await session.get(ChannelMessage, message_id)
            if message is None:
                return self.settings.channel_outbox_max_attempts
            final = message.attempts >= self.settings.channel_outbox_max_attempts
            message.status = "failed" if final else "retrying"
            message.error_message = error[:2_000]
            message.lease_until = None
            await session.commit()
            return message.attempts

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _text_chunks(content: str, max_bytes: int = 2_000) -> list[str]:
        """Keep each active text message under WeCom's 2048-byte boundary."""
        chunks: list[str] = []
        current: list[str] = []
        current_bytes = 0
        for character in content:
            encoded_bytes = len(character.encode("utf-8"))
            if current and current_bytes + encoded_bytes > max_bytes:
                chunks.append("".join(current))
                current = []
                current_bytes = 0
            current.append(character)
            current_bytes += encoded_bytes
        if current:
            chunks.append("".join(current))
        return chunks or [""]
