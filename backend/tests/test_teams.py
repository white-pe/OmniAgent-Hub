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


class DelegatingRuntimeClient:
    team_id = ""
    worker_id = ""
    calls: list[list[dict[str, object]]] = []

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
        self.calls.append(messages)
        system_prompt = str(messages[0]["content"])
        if "Coordinator Agent" in system_prompt:
            if messages[-1]["role"] == "tool":
                result = json.loads(str(messages[-1]["content"]))
                assert result["ok"] is True
                assert result["result"] == "成员研究结果：市场需求明确"
                yield ProviderTurnEvent(
                    kind="text_delta",
                    content="综合成员结论：市场需求明确，可以进入验证阶段。",
                )
                return
            assert tools is not None
            delegate = next(
                tool
                for tool in tools
                if tool["function"]["name"] == "delegate_to_agent"
            )
            assert self.worker_id in str(delegate)
            arguments = json.dumps(
                {
                    "team_id": self.team_id,
                    "target_agent_id": self.worker_id,
                    "task": "研究目标市场需求，只返回简明结论。",
                },
                ensure_ascii=False,
            )
            yield ProviderTurnEvent(
                kind="tool_call_delta",
                index=0,
                call_id="call_delegate_worker",
                name="delegate_to_agent",
                arguments=arguments,
            )
            return

        assert "Worker Agent" in system_prompt
        assert "研究目标市场需求" in str(messages[-1]["content"])
        assert "协调者的上下文或权限" in str(messages[-1]["content"])
        yield ProviderTurnEvent(kind="text_delta", content="成员研究结果：市场需求明确")


class ForgedDelegationClient:
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
            yield ProviderTurnEvent(
                kind="text_delta", content="我没有协调 Team 的委派权限。"
            )
            return
        assert tools is None
        yield ProviderTurnEvent(
            kind="tool_call_delta",
            index=0,
            call_id="call_forged_delegation",
            name="delegate_to_agent",
            arguments=json.dumps(
                {
                    "team_id": "forged-team",
                    "target_agent_id": "forged-agent",
                    "task": "越权任务",
                }
            ),
        )


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach a terminal state")


def test_team_crud_and_coordinator_delegates_to_isolated_child_run(
    tmp_path: Path,
) -> None:
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
    DelegatingRuntimeClient.calls = []

    with TestClient(application) as client:
        application.state.provider_client_factory = DelegatingRuntimeClient
        provider = client.post(
            "/api/providers",
            json={
                "name": "Team Provider",
                "base_url": "https://example.com/v1",
                "api_key": "sk-team-test",
                "models": [{"model_name": "team-model"}],
            },
        ).json()
        model_id = provider["models"][0]["id"]

        def create_agent(name: str, is_coordinator: bool) -> dict[str, object]:
            response = client.post(
                "/api/agents",
                json={
                    "name": name,
                    "description": f"{name} 的独立职责",
                    "provider_id": provider["id"],
                    "model_id": model_id,
                    "is_coordinator": is_coordinator,
                },
            )
            assert response.status_code == 201
            return response.json()

        coordinator = create_agent("Coordinator Agent", True)
        worker = create_agent("Worker Agent", False)
        invalid = client.post(
            "/api/teams",
            json={
                "name": "Invalid Team",
                "description": "",
                "coordinator_agent_id": worker["id"],
                "member_agent_ids": [coordinator["id"]],
            },
        )
        assert invalid.status_code == 409

        team_response = client.post(
            "/api/teams",
            json={
                "name": "Research Team",
                "description": "协调研究与汇总",
                "coordinator_agent_id": coordinator["id"],
                "member_agent_ids": [worker["id"]],
            },
        )
        assert team_response.status_code == 201
        team = team_response.json()
        assert [member["role"] for member in team["members"]] == [
            "member",
            "coordinator",
        ] or [member["role"] for member in team["members"]] == [
            "coordinator",
            "member",
        ]
        DelegatingRuntimeClient.team_id = team["id"]
        DelegatingRuntimeClient.worker_id = str(worker["id"])

        chat = client.post("/api/chats", json={"agent_id": coordinator["id"]}).json()
        run_response = client.post(
            f"/api/chats/{chat['id']}/runs",
            json={"content": "请让研究成员分析市场，然后给我综合结论。"},
        )
        root_run_id = run_response.json()["id"]
        root_run = wait_for_terminal(client, root_run_id)
        assert root_run["status"] == "completed"
        assert root_run["depth"] == 0
        assert root_run["output_text"].startswith("综合成员结论")

        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert [message["role"] for message in detail["messages"]] == [
            "user",
            "assistant",
        ]
        assert len(detail["runs"]) == 2
        child = next(run for run in detail["runs"] if run["parent_run_id"])
        assert child["parent_run_id"] == root_run_id
        assert child["agent_id"] == worker["id"]
        assert child["depth"] == 1
        assert child["status"] == "completed"
        assert len(detail["delegations"]) == 1
        delegation = detail["delegations"][0]
        assert delegation["parent_run_id"] == root_run_id
        assert delegation["child_run_id"] == child["id"]
        assert delegation["target_agent_name"] == "Worker Agent"
        assert delegation["status"] == "completed"
        assert delegation["result_text"] == "成员研究结果：市场需求明确"
        delegate_tool_call = next(
            call
            for call in detail["tool_calls"]
            if call["tool_name"] == "delegate_to_agent"
        )
        assert delegate_tool_call["status"] == "completed"

        with client.stream("GET", f"/api/runs/{root_run_id}/events") as response:
            event_body = response.read().decode("utf-8")
        assert "event: delegation.started" in event_body
        assert "event: delegation.completed" in event_body

        cannot_delete_history = client.delete(f"/api/teams/{team['id']}")
        assert cannot_delete_history.status_code == 409
        disabled = client.post(f"/api/teams/{team['id']}/toggle")
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"


def test_non_coordinator_forged_delegation_is_rejected(tmp_path: Path) -> None:
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
        application.state.provider_client_factory = ForgedDelegationClient
        provider = client.post(
            "/api/providers",
            json={
                "name": "Forged Team Provider",
                "base_url": "https://example.com/v1",
                "api_key": "sk-forged-team-test",
                "models": [{"model_name": "team-model"}],
            },
        ).json()
        agent = client.post(
            "/api/agents",
            json={
                "name": "Regular Agent",
                "description": "没有协调权限",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
                "is_coordinator": False,
            },
        ).json()
        chat = client.post("/api/chats", json={"agent_id": agent["id"]}).json()
        run_response = client.post(
            f"/api/chats/{chat['id']}/runs", json={"content": "尝试越权委派"}
        )
        run = wait_for_terminal(client, run_response.json()["id"])
        assert run["status"] == "completed"
        assert run["output_text"] == "我没有协调 Team 的委派权限。"
        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert detail["delegations"] == []
        tool_call = next(
            call
            for call in detail["tool_calls"]
            if call["tool_name"] == "delegate_to_agent"
        )
        assert tool_call["status"] == "rejected"
        assert "not active" in tool_call["error_message"]
