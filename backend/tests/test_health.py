from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.main import create_app


def test_health_reports_database_ready(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{database_path}",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "name": "OmniAgent",
        "version": "1.0.0",
        "environment": "test",
        "status": "ok",
        "database": "ok",
    }
