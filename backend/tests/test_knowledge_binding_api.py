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


def test_agent_knowledge_base_binding_api(tmp_path: Path) -> None:
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
        provider_response = client.post(
            "/api/providers",
            json={
                "name": "Knowledge Binding Provider",
                "base_url": "https://example.com/v1",
                "api_key": "sk-binding-test",
                "models": [{"model_name": "binding-model"}],
            },
        )
        assert provider_response.status_code == 201
        provider = provider_response.json()

        agent_response = client.post(
            "/api/agents",
            json={
                "name": "Knowledge Binding Agent",
                "description": "Tests knowledge access bindings",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )
        assert agent_response.status_code == 201
        agent = agent_response.json()

        knowledge_response = client.post(
            "/api/knowledge-bases",
            json={"name": "Binding API Docs"},
        )
        assert knowledge_response.status_code == 201
        knowledge_base = knowledge_response.json()

        base_path = f"/api/agents/{agent['id']}/knowledge-bases"
        assert client.get(base_path).json() == []

        create_binding = client.post(
            base_path,
            json={"knowledge_base_id": knowledge_base["id"]},
        )
        assert create_binding.status_code == 201
        assert create_binding.json()["enabled"] is True

        duplicate = client.post(
            base_path,
            json={"knowledge_base_id": knowledge_base["id"]},
        )
        assert duplicate.status_code == 409

        binding_path = f"{base_path}/{knowledge_base['id']}"
        disabled = client.patch(binding_path, json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        listed = client.get(base_path).json()
        assert len(listed) == 1
        assert listed[0]["knowledge_base_name"] == "Binding API Docs"
        assert listed[0]["enabled"] is False

        assert client.delete(binding_path).status_code == 204
        assert client.get(base_path).json() == []
        assert client.delete(binding_path).status_code == 404

        missing_agent = client.get("/api/agents/missing-agent/knowledge-bases")
        assert missing_agent.status_code == 404