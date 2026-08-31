"""Single-admin login, session inspection and logout endpoints."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from pawteam_api.security.auth import CSRF_COOKIE, SESSION_COOKIE

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class AuthStatus(BaseModel):
    auth_enabled: bool
    authenticated: bool
    username: str | None = None


def _client_key(request: Request) -> str:
    # Backend is private behind Nginx. A single shared bucket cannot be bypassed
    # by forging X-Forwarded-For and is appropriate for the one-admin boundary.
    return request.client.host if request.client else "admin"


def _set_session_cookies(
    response: Response, request: Request, token: str, csrf_token: str
) -> None:
    settings = request.app.state.settings
    max_age = settings.auth_session_hours * 3600
    common = {
        "max_age": max_age,
        "samesite": "strict",
        "secure": settings.is_production,
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **common)


@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request) -> AuthStatus:
    manager = request.app.state.auth_manager
    if not manager.enabled:
        return AuthStatus(auth_enabled=False, authenticated=True, username="admin")
    identity = manager.authenticate(request.cookies.get(SESSION_COOKIE))
    return AuthStatus(
        auth_enabled=True,
        authenticated=identity is not None,
        username=identity.username if identity else None,
    )


@router.post("/login", response_model=AuthStatus)
async def login(
    payload: LoginRequest, request: Request, response: Response
) -> AuthStatus:
    manager = request.app.state.auth_manager
    if not manager.enabled:
        return AuthStatus(auth_enabled=False, authenticated=True, username="admin")
    key = _client_key(request)
    if manager.rate_limiter.is_blocked(key):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")
    if not manager.verify_password(payload.password):
        manager.rate_limiter.record_failure(key)
        raise HTTPException(status_code=401, detail="管理员密码错误")
    manager.rate_limiter.reset(key)
    token, identity = manager.create_session()
    _set_session_cookies(response, request, token, identity.csrf_token)
    return AuthStatus(auth_enabled=True, authenticated=True, username=identity.username)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    secure = request.app.state.settings.is_production
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, samesite="strict")
