"""Server-side QR authorization sessions for WeCom intelligent bots."""

from __future__ import annotations

import base64
import io
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import segno

from pawteam_api.config import Settings

_AUTH_ORIGIN = "https://work.weixin.qq.com"
_SOURCE = "pawteam-lite"


class WeComQrError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeComBotCredentials:
    bot_id: str
    secret: str


@dataclass
class _AuthorizationSession:
    scode: str
    expires_at: datetime
    credentials: WeComBotCredentials | None = None
    failed_message: str | None = None


class WeComQrAuthorizationService:
    """Keep the provider poll token and resulting Secret off the browser."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, _AuthorizationSession] = {}

    async def start(self) -> tuple[str, str, int]:
        state = secrets.token_urlsafe(16)
        url = (
            f"{_AUTH_ORIGIN}/ai/qc/gen?source={_SOURCE}&state={state}"
            f"&timestamp={int(time.time() * 1000)}"
        )
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.channel_delivery_timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WeComQrError(f"Unable to request WeCom QR code: {exc}") from exc

        match = re.search(r"window\.settings\s*=\s*(\{[^<]+\})", response.text)
        if match is None:
            raise WeComQrError("WeCom QR page format has changed")
        try:
            settings = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise WeComQrError("WeCom QR page returned invalid settings") from exc
        scode = str(settings.get("scode", ""))
        auth_url = str(settings.get("auth_url", ""))
        if not scode or not auth_url:
            raise WeComQrError("WeCom QR page did not return authorization data")

        session_id = secrets.token_urlsafe(32)
        seconds = self.settings.channel_qr_session_seconds
        self._purge_expired()
        self.sessions[session_id] = _AuthorizationSession(
            scode=scode,
            expires_at=self._now() + timedelta(seconds=seconds),
        )
        return session_id, self._qrcode_data_url(auth_url), seconds

    async def poll(self, session_id: str) -> tuple[str, str | None]:
        session = self.sessions.get(session_id)
        if session is None or session.expires_at <= self._now():
            self.sessions.pop(session_id, None)
            return "expired", "二维码已过期，请重新获取"
        if session.credentials is not None:
            return "ready", None
        if session.failed_message is not None:
            return "failed", session.failed_message

        url = f"{_AUTH_ORIGIN}/ai/qc/query_result?scode={quote(session.scode)}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.channel_delivery_timeout_seconds
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise WeComQrError(f"Unable to query WeCom QR status: {exc}") from exc

        data = result.get("data", {}) if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            return "waiting", None
        status = str(data.get("status", "waiting")).lower()
        if status == "success":
            bot_info = data.get("bot_info", {})
            if not isinstance(bot_info, dict):
                bot_info = {}
            bot_id = str(bot_info.get("botid", ""))
            secret = str(bot_info.get("secret", ""))
            if bot_id and secret:
                session.credentials = WeComBotCredentials(bot_id, secret)
                return "ready", None
            session.failed_message = "企业微信授权成功但没有返回机器人凭据"
            return "failed", session.failed_message
        if status in {"expired", "fail", "failed", "cancelled", "canceled"}:
            session.failed_message = "企业微信授权未完成或已取消"
            return "failed", session.failed_message
        return "waiting", None

    def consume(self, session_id: str) -> WeComBotCredentials:
        session = self.sessions.get(session_id)
        if session is None or session.expires_at <= self._now():
            self.sessions.pop(session_id, None)
            raise WeComQrError("QR authorization session has expired")
        if session.credentials is None:
            raise WeComQrError("QR authorization has not completed")
        self.sessions.pop(session_id, None)
        return session.credentials

    def _purge_expired(self) -> None:
        now = self._now()
        for session_id in [
            key for key, value in self.sessions.items() if value.expires_at <= now
        ]:
            self.sessions.pop(session_id, None)

    @staticmethod
    def _qrcode_data_url(url: str) -> str:
        qr = segno.make(url, error="m")
        buffer = io.BytesIO()
        qr.save(buffer, kind="png", scale=6, border=2)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
