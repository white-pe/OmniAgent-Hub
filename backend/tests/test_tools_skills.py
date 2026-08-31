import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base
from pawteam_api.providers.client import ProviderTurnEvent
from pawteam_api.tools.registry import ToolContext, ToolRegistry
from pawteam_api.workspaces.store import WorkspaceStore


class ToolRuntimeClient:
    calls: list[tuple[list[dict[str, object]], list[dict[str, object]] | None]] = []

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        del base_url, api_key, timeout_seconds

    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        temperature: float,
        tools: list[dict[str, object]] | None,
    ) -> AsyncIterator[ProviderTurnEvent]:
        del model, temperature
        self.calls.append((messages, tools))
        if messages[-1]["role"] == "tool":
            result = json.loads(str(messages[-1]["content"]))
            assert result["ok"] is True
            assert "研究背景" in result["data"]["content"]
            yield ProviderTurnEvent(kind="text_delta", content="已读取研究背景")
            return
        yield ProviderTurnEvent(
            kind="tool_call_delta",
            index=0,
            call_id="call_profile",
            name="read_workspace_",
            arguments='{"path":"PRO',
        )
        yield ProviderTurnEvent(
            kind="tool_call_delta",
            index=0,
            name="file",
            arguments='FILE.md"}',
        )


class ForgedToolRuntimeClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        del base_url, api_key, timeout_seconds

    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        temperature: float,
        tools: list[dict[str, object]] | None,
    ) -> AsyncIterator[ProviderTurnEvent]:
        del model, temperature
        if messages[-1]["role"] == "tool":
            result = json.loads(str(messages[-1]["content"]))
            assert result["status"] == "rejected"
            yield ProviderTurnEvent(kind="text_delta", content="该工具没有获得授权")
            return
        assert tools is None
        yield ProviderTurnEvent(
            kind="tool_call_delta",
            index=0,
            call_id="call_forged",
            name="read_workspace_file",
            arguments='{"path":"PROFILE.md"}',
        )


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def provider_payload() -> dict[str, object]:
    return {
        "name": "Tool Provider",
        "base_url": "https://example.com/v1",
        "api_key": "sk-tool-test",
        "models": [{"model_name": "tool-model"}],
    }


def create_agent(client: TestClient) -> dict[str, object]:
    provider = client.post("/api/providers", json=provider_payload()).json()
    response = client.post(
        "/api/agents",
        json={
            "name": "Tool Agent",
            "description": "测试 Skill 与 Tool",
            "provider_id": provider["id"],
            "model_id": provider["models"][0]["id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach a terminal state")


def test_skill_crud_and_enabled_tool_loop(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        run_event_poll_interval_seconds=0.01,
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)
    ToolRuntimeClient.calls = []

    with TestClient(application) as client:
        application.state.provider_client_factory = ToolRuntimeClient
        agent = create_agent(client)
        profile_response = client.put(
            f"/api/agents/{agent['id']}/files/PROFILE.md",
            json={"content": "# 研究背景\n\n只使用可靠来源。", "expected_version": 1},
        )
        assert profile_response.status_code == 200

        skill_response = client.post(
            f"/api/agents/{agent['id']}/skills",
            json={
                "name": "source-check",
                "description": "回答前检查来源",
                "content": "# 来源检查\n\n先检查证据，再给结论。",
            },
        )
        assert skill_response.status_code == 201
        skill = skill_response.json()
        assert skill["path"] == "skills/source-check"
        skill_file = (
            tmp_path
            / "workspaces"
            / str(agent["workspace_path"])
            / "skills"
            / "source-check"
            / "SKILL.md"
        )
        assert skill_file.read_text(encoding="utf-8").startswith("# 来源检查")

        tools = client.get(f"/api/agents/{agent['id']}/tools").json()
        assert all(tool["enabled"] is False for tool in tools)
        toggled = client.post(
            f"/api/agents/{agent['id']}/tools/read_workspace_file/toggle"
        )
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is True

        chat = client.post("/api/chats", json={"agent_id": agent["id"]}).json()
        run_response = client.post(
            f"/api/chats/{chat['id']}/runs", json={"content": "读取研究背景"}
        )
        run = wait_for_terminal(client, run_response.json()["id"])
        assert run["status"] == "completed"
        assert run["output_text"] == "已读取研究背景"
        assert len(ToolRuntimeClient.calls) == 2
        system_prompt = str(ToolRuntimeClient.calls[0][0][0]["content"])
        assert "已启用 Skill / source-check" in system_prompt
        definitions = ToolRuntimeClient.calls[0][1]
        assert definitions is not None
        assert definitions[0]["function"]["name"] == "read_workspace_file"

        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert len(detail["tool_calls"]) == 1
        tool_call = detail["tool_calls"][0]
        assert tool_call["status"] == "completed"
        assert tool_call["arguments"] == {"path": "PROFILE.md"}
        assert "研究背景" in tool_call["result"]["data"]["content"]

        with client.stream("GET", f"/api/runs/{run['id']}/events") as response:
            event_body = response.read().decode("utf-8")
        assert "event: tool.requested" in event_body
        assert "event: tool.started" in event_body
        assert "event: tool.completed" in event_body

        stale_update = client.put(
            f"/api/agents/{agent['id']}/skills/source-check",
            json={"expected_version": 999, "description": "冲突"},
        )
        assert stale_update.status_code == 409
        assert (
            client.delete(f"/api/agents/{agent['id']}/skills/source-check").status_code
            == 204
        )
        assert not skill_file.exists()


def test_forged_disabled_tool_call_is_audited_and_rejected(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        run_event_poll_interval_seconds=0.01,
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)

    with TestClient(application) as client:
        application.state.provider_client_factory = ForgedToolRuntimeClient
        agent = create_agent(client)
        chat = client.post("/api/chats", json={"agent_id": agent["id"]}).json()
        run_response = client.post(
            f"/api/chats/{chat['id']}/runs", json={"content": "尝试越权读取"}
        )
        run = wait_for_terminal(client, run_response.json()["id"])
        assert run["status"] == "completed"
        assert run["output_text"] == "该工具没有获得授权"
        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert detail["tool_calls"][0]["status"] == "rejected"
        assert "not enabled" in detail["tool_calls"][0]["error_message"]


def test_workspace_reader_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'unused.db'}",
    )
    store = WorkspaceStore(settings)
    staging = store.prepare("agent-1", "Path Agent", "测试路径边界")
    workspace_path = store.finalize(staging, "agent-1")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "workspaces" / workspace_path / "escape.txt").symlink_to(outside)
    registry = ToolRegistry(settings, store)
    context = ToolContext(
        agent_id="agent-1",
        run_id="run-1",
        workspace_path=workspace_path,
        channel="console",
    )

    traversal = asyncio.run(
        registry.execute(
            name="read_workspace_file",
            raw_arguments='{"path":"../outside.txt"}',
            enabled_names={"read_workspace_file"},
            context=context,
        )
    )
    symlink = asyncio.run(
        registry.execute(
            name="read_workspace_file",
            raw_arguments='{"path":"escape.txt"}',
            enabled_names={"read_workspace_file"},
            context=context,
        )
    )
    assert traversal.status == "failed"
    assert symlink.status == "failed"
    assert "secret" not in json.dumps(symlink.payload)
