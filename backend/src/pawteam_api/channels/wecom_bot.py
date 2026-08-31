"""WeCom intelligent-bot WebSocket connections and runtime bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.channels.ingress import ChannelIngressService
from pawteam_api.config import Settings
from pawteam_api.models import Channel
from pawteam_api.security.secret_store import SecretStore, SecretStoreError

logger = logging.getLogger(__name__)


class WeComBotError(RuntimeError):
    pass


InboundHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RunStarter(Protocol):
    def start(self, run_id: str) -> None: ...


class OutboundStarter(Protocol):
    def dispatch(self, message_id: str) -> None: ...


class BotConnection(Protocol):
    status: str

    def start(self, main_loop: asyncio.AbstractEventLoop) -> None: ...

    async def stop(self) -> None: ...

    async def send_text(self, chat_id: str, content: str) -> None: ...


class WeComBotConnection:
    """Run one SDK client in its own event-loop thread."""

    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        max_reconnect_attempts: int,
        on_message: InboundHandler,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.max_reconnect_attempts = max_reconnect_attempts
        self.on_message = on_message
        self.status = "stopped"
        self._client: Any = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self, main_loop: asyncio.AbstractEventLoop) -> None:
        from aibot import WSClient, WSClientOptions

        if self._thread is not None and self._thread.is_alive():
            return
        self._main_loop = main_loop
        self.status = "connecting"
        self._client = WSClient(
            WSClientOptions(
                bot_id=self.bot_id,
                secret=self.secret,
                max_reconnect_attempts=self.max_reconnect_attempts,
            )
        )
        self._client.on("authenticated", self._authenticated)
        self._client.on("disconnected", self._disconnected)
        self._client.on("reconnecting", self._reconnecting)
        self._client.on("error", self._error)
        self._client.on("message", self._message)
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"wecom-bot-{self.bot_id[:8]}",
        )
        self._thread.start()

    async def stop(self) -> None:
        loop = self._ws_loop
        if self._client is not None and loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._client.disconnect)
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5)
        self._client = None
        self._thread = None
        self.status = "stopped"

    async def send_text(self, chat_id: str, content: str) -> None:
        if self.status != "connected" or self._client is None:
            raise WeComBotError("WeCom intelligent bot is not connected")
        loop = self._ws_loop
        if loop is None or not loop.is_running():
            raise WeComBotError("WeCom intelligent bot event loop is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._client.send_message(
                chat_id,
                {"msgtype": "markdown", "markdown": {"content": content}},
            ),
            loop,
        )
        try:
            await asyncio.wrap_future(future)
        except Exception as exc:
            raise WeComBotError(f"WeCom bot send failed: {exc}") from exc

    def _run(self) -> None:
        if sys.platform == "darwin":
            loop = asyncio.SelectorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ws_loop = loop
        try:
            loop.run_until_complete(self._client.connect())
            loop.run_forever()
        except Exception as exc:
            self.status = "error"
            logger.error("WeCom bot connection failed: %s", exc)
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self._ws_loop = None

    def _message(self, frame: dict[str, Any]) -> None:
        loop = self._main_loop
        if loop is None or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self.on_message(frame), loop)
        future.add_done_callback(self._log_inbound_result)

    @staticmethod
    def _log_inbound_result(future: Future[None]) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("WeCom bot inbound processing failed")

    def _authenticated(self, *_: object) -> None:
        self.status = "connected"

    def _disconnected(self, *_: object) -> None:
        self.status = "connecting"

    def _reconnecting(self, *_: object) -> None:
        self.status = "connecting"

    def _error(self, error: object) -> None:
        self.status = "error"
        logger.error("WeCom bot SDK error: %s", error)


BotConnectionFactory = Callable[..., BotConnection]


class WeComBotManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        secret_store: SecretStore,
        connection_factory: BotConnectionFactory = WeComBotConnection,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.secret_store = secret_store
        self.connection_factory = connection_factory
        self.connections: dict[str, BotConnection] = {}
        self.errors: dict[str, str] = {}
        self.run_starter: RunStarter | None = None
        self.outbound_starter: OutboundStarter | None = None
        self.main_loop: asyncio.AbstractEventLoop | None = None

    def bind_runtime(
        self, run_starter: RunStarter, outbound_starter: OutboundStarter
    ) -> None:
        self.run_starter = run_starter
        self.outbound_starter = outbound_starter

    async def start_all(self) -> None:
        self.main_loop = asyncio.get_running_loop()
        try:
            async with self.session_factory() as session:
                ids = (
                    await session.scalars(
                        select(Channel.id).where(
                            Channel.kind == "wecom_bot", Channel.status == "active"
                        )
                    )
                ).all()
        except OperationalError as error:
            if "no such table: channels" not in str(error):
                raise
            return
        for channel_id in ids:
            try:
                await self.start_channel(channel_id)
            except WeComBotError as exc:
                self.errors[channel_id] = str(exc)
                logger.error(
                    "Unable to start WeCom bot channel %s: %s", channel_id, exc
                )

    async def start_channel(self, channel_id: str) -> None:
        await self.stop_channel(channel_id)
        self.errors.pop(channel_id, None)
        async with self.session_factory() as session:
            channel = await session.get(Channel, channel_id)
            if (
                channel is None
                or channel.kind != "wecom_bot"
                or channel.status != "active"
            ):
                return
            try:
                raw = json.loads(self.secret_store.get(channel.secret_ref))
                bot_id = str(channel.config_json["bot_id"])
                secret = str(raw["secret"])
            except (SecretStoreError, ValueError, KeyError, TypeError) as exc:
                raise WeComBotError("Invalid WeCom bot credentials") from exc
        connection = self.connection_factory(
            bot_id=bot_id,
            secret=secret,
            max_reconnect_attempts=self.settings.channel_wecom_reconnect_attempts,
            on_message=lambda frame: self._receive(channel_id, frame),
        )
        self.connections[channel_id] = connection
        try:
            connection.start(self.main_loop or asyncio.get_running_loop())
        except Exception as exc:
            self.connections.pop(channel_id, None)
            self.errors[channel_id] = str(exc)
            raise WeComBotError(f"Unable to start WeCom bot: {exc}") from exc

    async def stop_channel(self, channel_id: str) -> None:
        self.errors.pop(channel_id, None)
        connection = self.connections.pop(channel_id, None)
        if connection is not None:
            await connection.stop()

    async def shutdown(self) -> None:
        for channel_id in list(self.connections):
            await self.stop_channel(channel_id)

    async def send_text(self, channel_id: str, chat_id: str, content: str) -> None:
        connection = self.connections.get(channel_id)
        if connection is None:
            raise WeComBotError("WeCom intelligent bot is not running")
        await connection.send_text(chat_id, content)

    def status(self, channel_id: str) -> str:
        if channel_id in self.errors:
            return "error"
        connection = self.connections.get(channel_id)
        return connection.status if connection is not None else "stopped"

    async def _receive(self, channel_id: str, frame: dict[str, Any]) -> None:
        body = frame.get("body", {})
        if not isinstance(body, dict) or body.get("msgtype") != "text":
            return
        text_body = body.get("text", {})
        sender_body = body.get("from", {})
        if not isinstance(text_body, dict) or not isinstance(sender_body, dict):
            return
        content = str(text_body.get("content", "")).strip()
        sender_id = str(sender_body.get("userid", "")).strip()
        chat_id = str(body.get("chatid", "")).strip() or sender_id
        message_id = str(body.get("msgid", "")).strip()
        if not message_id:
            message_id = f"{sender_id}:{body.get('send_time', '')}"
        if not content or not sender_id or not chat_id:
            return

        async with self.session_factory() as session:
            channel = await session.get(Channel, channel_id)
            if channel is None or channel.status != "active":
                return
            result = await ChannelIngressService(session).receive_text(
                channel=channel,
                external_conversation_id=chat_id,
                external_user_id=sender_id,
                external_message_id=message_id,
                content=content,
            )
        if result.run_id is not None and not result.duplicate and self.run_starter:
            self.run_starter.start(result.run_id)
        if result.outbound_message_id is not None and self.outbound_starter:
            self.outbound_starter.dispatch(result.outbound_message_id)
