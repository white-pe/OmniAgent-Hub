import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def test_knowledge_base_api_crud_and_errors(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)

    with TestClient(application) as client:
        assert client.get("/api/knowledge-bases").json() == []

        created_response = client.post(
            "/api/knowledge-bases",
            json={
                "name": "Engineering Docs",
                "description": "Internal references",
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["version"] == 1
        assert created["enabled"] is True

        duplicate_response = client.post(
            "/api/knowledge-bases",
            json={"name": "Engineering Docs"},
        )
        assert duplicate_response.status_code == 409

        listed = client.get("/api/knowledge-bases").json()
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]

        updated_response = client.put(
            f"/api/knowledge-bases/{created['id']}",
            json={
                "expected_version": 1,
                "description": "",
                "enabled": False,
            },
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["description"] == ""
        assert updated["enabled"] is False
        assert updated["version"] == 2

        stale_response = client.put(
            f"/api/knowledge-bases/{created['id']}",
            json={
                "expected_version": 1,
                "name": "Stale Name",
            },
        )
        assert stale_response.status_code == 409

        missing_response = client.get("/api/knowledge-bases/missing-id")
        assert missing_response.status_code == 404

        stale_delete = client.delete(
            f"/api/knowledge-bases/{created['id']}?expected_version=1"
        )
        assert stale_delete.status_code == 409

        deleted = client.delete(
            f"/api/knowledge-bases/{created['id']}?expected_version=2"
        )
        assert deleted.status_code == 204

        missing_after_delete = client.get(
            f"/api/knowledge-bases/{created['id']}"
        )
        assert missing_after_delete.status_code == 404

        invalid_payload = client.post(
            "/api/knowledge-bases",
            json={"name": "   "},
        )
        assert invalid_payload.status_code == 422