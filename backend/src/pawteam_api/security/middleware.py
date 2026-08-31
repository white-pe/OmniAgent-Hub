"""ASGI authentication boundary that remains compatible with streaming responses."""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from pawteam_api.security.auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    AuthManager,
)

PUBLIC_EXACT_PATHS = {
    "/api/auth/login",
    "/api/auth/status",
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
}
PUBLIC_PREFIXES = ("/api/channel-webhooks/wecom/",)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ConsoleSecurityMiddleware:
    def __init__(self, app: ASGIApp, auth: AuthManager) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.auth.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in PUBLIC_EXACT_PATHS or path.startswith(PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        identity = self.auth.authenticate(_cookie(headers, SESSION_COOKIE))
        if identity is None:
            await _json_error(401, "登录已失效，请重新登录", scope, receive, send)
            return

        if scope.get("method") in UNSAFE_METHODS:
            csrf_cookie = _cookie(headers, CSRF_COOKIE)
            csrf_header = headers.get(CSRF_HEADER)
            if not (
                csrf_cookie
                and csrf_header
                and hmac_compare(csrf_cookie, csrf_header)
                and hmac_compare(csrf_cookie, identity.csrf_token)
            ):
                await _json_error(403, "CSRF validation failed", scope, receive, send)
                return

        scope.setdefault("state", {})["identity"] = identity
        await self.app(scope, receive, send)


def _cookie(headers: Headers, name: str) -> str | None:
    for pair in headers.get("cookie", "").split(";"):
        key, separator, value = pair.strip().partition("=")
        if separator and key == name:
            return value
    return None


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


async def _json_error(
    status_code: int,
    detail: str,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response = JSONResponse({"detail": detail}, status_code=status_code)
    await response(scope, receive, send)
