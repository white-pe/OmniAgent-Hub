from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.main import create_app


def auth_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "data_dir": tmp_path,
        "secrets_dir": tmp_path / "secrets",
        "workspaces_dir": tmp_path / "workspaces",
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "admin_password": "correct-horse-battery-staple",
        "auth_secret_key": "a" * 48,
    }
    values.update(overrides)
    return Settings(**values)


def test_login_session_and_csrf_boundary(tmp_path: Path) -> None:
    with TestClient(create_app(auth_settings(tmp_path))) as client:
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.post("/api/auth/logout").status_code == 401
        bad_login = client.post("/api/auth/login", json={"password": "wrong"})
        assert bad_login.status_code == 401

        login = client.post(
            "/api/auth/login", json={"password": "correct-horse-battery-staple"}
        )
        assert login.status_code == 200
        assert login.json() == {
            "auth_enabled": True,
            "authenticated": True,
            "username": "admin",
        }
        assert client.cookies.get("pawteam_session")
        csrf = client.cookies.get("pawteam_csrf")
        assert csrf
        assert client.get("/api/auth/status").json()["authenticated"] is True

        assert client.post("/api/auth/logout").status_code == 403
        assert (
            client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code
            == 204
        )
        assert client.get("/api/auth/status").json()["authenticated"] is False


def test_health_checks_remain_public_when_auth_is_enabled(tmp_path: Path) -> None:
    with TestClient(create_app(auth_settings(tmp_path))) as client:
        assert client.get("/api/health/live").status_code == 204
        assert client.get("/api/health/ready").status_code == 200


def test_production_configuration_fails_closed(tmp_path: Path) -> None:
    settings = auth_settings(
        tmp_path,
        environment="production",
        admin_password=None,
        auth_secret_key=None,
        secret_key=None,
    )
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app(settings)
