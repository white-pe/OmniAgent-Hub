"""Small single-admin session authentication for the self-hosted console."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from pawteam_api.config import Settings

SESSION_COOKIE = "pawteam_session"
CSRF_COOKIE = "pawteam_csrf"
CSRF_HEADER = "x-csrf-token"


@dataclass(frozen=True)
class SessionIdentity:
    username: str
    csrf_token: str
    expires_at: int


class LoginRateLimiter:
    """Per-process limiter for the intentionally single-process deployment."""

    def __init__(self, attempts: int = 8, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def is_blocked(self, key: str) -> bool:
        failures = self._active(key)
        return len(failures) >= self.attempts

    def record_failure(self, key: str) -> None:
        self._active(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def _active(self, key: str) -> deque[float]:
        failures = self._failures[key]
        cutoff = time.monotonic() - self.window_seconds
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures


class AuthManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rate_limiter = LoginRateLimiter()
        self._development_signing_key = secrets.token_bytes(32)

    @property
    def enabled(self) -> bool:
        return self.settings.auth_enabled

    def verify_password(self, candidate: str) -> bool:
        expected = self.settings.admin_password
        if expected is None:
            return False
        return secrets.compare_digest(candidate, expected.get_secret_value())

    def create_session(self) -> tuple[str, SessionIdentity]:
        now = int(time.time())
        identity = SessionIdentity(
            username="admin",
            csrf_token=secrets.token_urlsafe(32),
            expires_at=now + self.settings.auth_session_hours * 3600,
        )
        payload = self._encode(
            {
                "sub": identity.username,
                "csrf": identity.csrf_token,
                "exp": identity.expires_at,
                "nonce": secrets.token_urlsafe(12),
            }
        )
        signature = hmac.new(self._signing_key(), payload, hashlib.sha256).digest()
        return (
            f"{payload.decode()}.{self._encode_bytes(signature).decode()}",
            identity,
        )

    def authenticate(self, token: str | None) -> SessionIdentity | None:
        if not token:
            return None
        try:
            payload_text, signature_text = token.split(".", 1)
            payload = payload_text.encode()
            signature = self._decode_bytes(signature_text.encode())
            expected = hmac.new(self._signing_key(), payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            data = json.loads(self._decode_bytes(payload))
            identity = SessionIdentity(
                username=str(data["sub"]),
                csrf_token=str(data["csrf"]),
                expires_at=int(data["exp"]),
            )
            if identity.expires_at <= int(time.time()):
                return None
            return identity
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _signing_key(self) -> bytes:
        configured = self.settings.auth_secret_key
        if configured is not None:
            return configured.get_secret_value().encode()
        # Development-only fallback. Sessions intentionally expire after a restart.
        return self._development_signing_key

    @staticmethod
    def _encode(data: dict[str, object]) -> bytes:
        raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
        return AuthManager._encode_bytes(raw)

    @staticmethod
    def _encode_bytes(value: bytes) -> bytes:
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    @staticmethod
    def _decode_bytes(value: bytes) -> bytes:
        return base64.urlsafe_b64decode(value + b"=" * (-len(value) % 4))
