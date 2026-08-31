import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base
from pawteam_api.workspaces.store import (
    CORE_WORKSPACE_FILES,
    WorkspaceError,
    WorkspaceStore,
)


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def provider_payload(name: str, model_name: str) -> dict[str, object]:
    return {
        "name": name,
        "base_url": "https://example.com/v1",
        "api_key": f"sk-{name}",
        "models": [{"model_name": model_name}],
    }


def test_agents_have_isolated_persistent_workspaces(tmp_path: Path) -> None:
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
            "/api/providers", json=provider_payload("Provider A", "model-a")
        )
        assert provider_response.status_code == 201
        provider = provider_response.json()
        provider_id = provider["id"]
        model_id = provider["models"][0]["id"]

        agent_a_response = client.post(
            "/api/agents",
            json={
                "name": "Research Agent",
                "description": "负责资料研究",
                "provider_id": provider_id,
                "model_id": model_id,
            },
        )
        assert agent_a_response.status_code == 201
        agent_a = agent_a_response.json()
        agent_a_id = agent_a["id"]
        assert agent_a["version"] == 1
        assert agent_a["status"] == "active"

        agent_b_response = client.post(
            "/api/agents",
            json={
                "name": "Writing Agent",
                "description": "负责内容写作",
                "provider_id": provider_id,
                "model_id": model_id,
            },
        )
        assert agent_b_response.status_code == 201
        agent_b = agent_b_response.json()
        agent_b_id = agent_b["id"]

        workspace_a = settings.workspaces_dir / agent_a["workspace_path"]
        workspace_b = settings.workspaces_dir / agent_b["workspace_path"]
        assert {path.name for path in workspace_a.iterdir()} == set(
            CORE_WORKSPACE_FILES
        )
        assert {path.name for path in workspace_b.iterdir()} == set(
            CORE_WORKSPACE_FILES
        )
        assert workspace_a != workspace_b

        soul_a = client.get(f"/api/agents/{agent_a_id}/files/SOUL.md").json()
        soul_b_before = client.get(f"/api/agents/{agent_b_id}/files/SOUL.md").json()
        new_soul = "# 研究专家\n\n只给出有来源支撑的结论。\n"
        update_file_response = client.put(
            f"/api/agents/{agent_a_id}/files/SOUL.md",
            json={"content": new_soul, "expected_version": soul_a["agent_version"]},
        )
        assert update_file_response.status_code == 200
        assert update_file_response.json()["content"] == new_soul
        assert update_file_response.json()["agent_version"] == 2
        assert (
            client.get(f"/api/agents/{agent_b_id}/files/SOUL.md").json()["content"]
            == soul_b_before["content"]
        )

        stale_update = client.put(
            f"/api/agents/{agent_a_id}",
            json={"expected_version": 1, "description": "过期编辑"},
        )
        assert stale_update.status_code == 409

        update_agent_response = client.put(
            f"/api/agents/{agent_a_id}",
            json={"expected_version": 2, "description": "研究并核对可靠来源"},
        )
        assert update_agent_response.status_code == 200
        assert update_agent_response.json()["version"] == 3

        toggle_response = client.post(f"/api/agents/{agent_a_id}/toggle")
        assert toggle_response.status_code == 200
        assert toggle_response.json()["status"] == "disabled"
        assert toggle_response.json()["version"] == 4

        invalid_file_response = client.get(f"/api/agents/{agent_a_id}/files/secrets.md")
        assert invalid_file_response.status_code == 404

        provider_in_use_response = client.delete(f"/api/providers/{provider_id}")
        assert provider_in_use_response.status_code == 409

        remove_used_model_response = client.put(
            f"/api/providers/{provider_id}",
            json={"models": [{"model_name": "replacement-model"}]},
        )
        assert remove_used_model_response.status_code == 409
        assert "used by an Agent" in remove_used_model_response.json()["detail"]

    restarted_application = create_app(settings)
    with TestClient(restarted_application) as restarted_client:
        persisted_agents = restarted_client.get("/api/agents").json()
        assert [agent["name"] for agent in persisted_agents] == [
            "Research Agent",
            "Writing Agent",
        ]
        assert (
            restarted_client.get(f"/api/agents/{agent_a_id}/files/SOUL.md").json()[
                "content"
            ]
            == new_soul
        )

        assert restarted_client.delete(f"/api/agents/{agent_a_id}").status_code == 204
        assert restarted_client.delete(f"/api/agents/{agent_b_id}").status_code == 204
        assert not workspace_a.exists()
        assert not workspace_b.exists()
        delete_provider_response = restarted_client.delete(
            f"/api/providers/{provider_id}"
        )
        assert delete_provider_response.status_code == 204


def test_agent_rejects_model_from_another_provider(tmp_path: Path) -> None:
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
        provider_a = client.post(
            "/api/providers", json=provider_payload("Provider A", "model-a")
        ).json()
        provider_b = client.post(
            "/api/providers", json=provider_payload("Provider B", "model-b")
        ).json()
        response = client.post(
            "/api/agents",
            json={
                "name": "Invalid Agent",
                "provider_id": provider_a["id"],
                "model_id": provider_b["models"][0]["id"],
            },
        )

    assert response.status_code == 409
    assert "does not belong" in response.json()["detail"]
    assert list(settings.workspaces_dir.glob("*")) == []


def test_workspace_store_never_purges_its_root(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
    )
    store = WorkspaceStore(settings)

    with pytest.raises(WorkspaceError, match="root cannot"):
        store.purge(store.root)
