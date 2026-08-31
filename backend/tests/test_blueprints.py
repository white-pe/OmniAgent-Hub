import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base


class FakeBlueprintClient:
    output: dict[str, object] = {}

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        del base_url, api_key, timeout_seconds

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del model, prompt, system_prompt, temperature, max_tokens
        return f"```json\n{json.dumps(self.output, ensure_ascii=False)}\n```"


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def valid_blueprint() -> dict[str, object]:
    return {
        "name": "FastAPI 代码审查员",
        "description": "审查 FastAPI 项目的正确性、安全性和可维护性",
        "role": "资深 Python 代码审查工程师",
        "goals": ["发现高风险缺陷", "提供可执行的修复建议"],
        "tone": "严格、直接、基于证据",
        "rules": ["先列风险，再给建议", "不确定时明确说明"],
        "requested_tools": ["read_workspace_file"],
        "requested_skills": ["code-review"],
        "model_hint": "reasoning",
        "is_coordinator": False,
    }


def provider_payload() -> dict[str, object]:
    return {
        "name": "Blueprint Provider",
        "base_url": "https://example.com/v1",
        "api_key": "sk-blueprint-test",
        "models": [{"model_name": "blueprint-model"}],
    }


def test_blueprint_is_reviewed_before_it_creates_an_agent(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)
    FakeBlueprintClient.output = valid_blueprint()

    with TestClient(application) as client:
        application.state.provider_client_factory = FakeBlueprintClient
        provider = client.post("/api/providers", json=provider_payload()).json()
        generate_response = client.post(
            "/api/agent-blueprints/generate",
            json={
                "description": (
                    "创建一个严格的 FastAPI 代码审查助手，先指出风险再给建议。"
                ),
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )

        assert generate_response.status_code == 201
        draft = generate_response.json()
        assert draft["status"] == "draft"
        assert draft["blueprint"]["name"] == "FastAPI 代码审查员"
        assert len(draft["warnings"]) == 2
        assert client.get("/api/agents").json() == []
        assert list(settings.workspaces_dir.iterdir()) == []

        edited_blueprint = draft["blueprint"]
        edited_blueprint["name"] = "FastAPI 安全审查员"
        edited_blueprint["rules"].append("任何结论都要给出证据")
        apply_response = client.post(
            "/api/agents/from-blueprint",
            json={
                "draft_id": draft["draft_id"],
                "blueprint": edited_blueprint,
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )

        assert apply_response.status_code == 200
        agent = apply_response.json()
        assert agent["name"] == "FastAPI 安全审查员"
        assert agent["version"] == 1
        workspace = settings.workspaces_dir / agent["workspace_path"]
        assert "任何结论都要给出证据" in (workspace / "AGENTS.md").read_text()
        assert "资深 Python 代码审查工程师" in (workspace / "SOUL.md").read_text()
        assert "code-review" in (workspace / "PROFILE.md").read_text()

        applied_draft = client.get(f"/api/agent-blueprints/{draft['draft_id']}").json()
        assert applied_draft["status"] == "applied"
        assert applied_draft["applied_agent_id"] == agent["id"]

        duplicate_apply = client.post(
            "/api/agents/from-blueprint",
            json={
                "draft_id": draft["draft_id"],
                "blueprint": edited_blueprint,
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )
        assert duplicate_apply.status_code == 409
        assert len(client.get("/api/agents").json()) == 1

        duplicate_name_blueprint = valid_blueprint()
        duplicate_name_blueprint["name"] = agent["name"]
        FakeBlueprintClient.output = duplicate_name_blueprint
        duplicate_name_draft = client.post(
            "/api/agent-blueprints/generate",
            json={
                "description": "再生成一个名称冲突的草案，用于验证事务回滚和目录清理。",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        ).json()
        duplicate_name_apply = client.post(
            "/api/agents/from-blueprint",
            json={
                "draft_id": duplicate_name_draft["draft_id"],
                "blueprint": duplicate_name_draft["blueprint"],
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )
        assert duplicate_name_apply.status_code == 409
        assert (
            client.get(
                f"/api/agent-blueprints/{duplicate_name_draft['draft_id']}"
            ).json()["status"]
            == "draft"
        )
        assert len(list(settings.workspaces_dir.iterdir())) == 1


def test_cancelled_blueprint_has_no_agent_or_workspace(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)
    FakeBlueprintClient.output = valid_blueprint()

    with TestClient(application) as client:
        application.state.provider_client_factory = FakeBlueprintClient
        provider = client.post("/api/providers", json=provider_payload()).json()
        draft = client.post(
            "/api/agent-blueprints/generate",
            json={
                "description": "创建一个只生成草案、随后由用户取消的代码审查助手。",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        ).json()
        cancel_response = client.post(
            f"/api/agent-blueprints/{draft['draft_id']}/cancel"
        )

        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
        assert client.get("/api/agents").json() == []
        assert list(settings.workspaces_dir.iterdir()) == []


def test_model_cannot_put_unsupported_tool_in_blueprint(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)
    unsafe_blueprint = valid_blueprint()
    unsafe_blueprint["requested_tools"] = ["delete_everything"]
    FakeBlueprintClient.output = unsafe_blueprint

    with TestClient(application) as client:
        application.state.provider_client_factory = FakeBlueprintClient
        provider = client.post("/api/providers", json=provider_payload()).json()
        response = client.post(
            "/api/agent-blueprints/generate",
            json={
                "description": "创建一个可能要求危险工具的助手，并验证服务端拒绝它。",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
            },
        )

        assert response.status_code == 502
        assert "not a valid Agent Blueprint" in response.json()["detail"]
        assert client.get("/api/agents").json() == []
        assert list(settings.workspaces_dir.iterdir()) == []
