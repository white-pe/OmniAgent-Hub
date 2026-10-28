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


def test_knowledge_document_api(tmp_path: Path) -> None:
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
        knowledge_response = client.post(
            "/api/knowledge-bases",
            json={"name": "Document API Docs"},
        )
        assert knowledge_response.status_code == 201
        knowledge_base = knowledge_response.json()
        documents_path = (
            f"/api/knowledge-bases/{knowledge_base['id']}/documents"
        )

        assert client.get(documents_path).json() == []

        created_response = client.post(
            documents_path,
            json={"title": "  API Guide  "},
        )
        assert created_response.status_code == 201
        document = created_response.json()
        assert document["knowledge_base_id"] == knowledge_base["id"]
        assert document["title"] == "API Guide"
        assert document["status"] == "active"
        assert "storage_key" not in document

        listed = client.get(documents_path)
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == document["id"]

        invalid_payload = client.post(
            documents_path,
            json={"title": "API Guide", "storage_key": "user-controlled"},
        )
        assert invalid_payload.status_code == 422

        missing_path = "/api/knowledge-bases/missing-id/documents"
        assert client.get(missing_path).status_code == 404
        assert client.post(
            missing_path,
            json={"title": "Orphan Document"},
        ).status_code == 404