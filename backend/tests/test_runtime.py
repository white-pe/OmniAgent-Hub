import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base
from pawteam_api.providers.client import ProviderTurnEvent


class RecordingRuntimeClient:
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
        del model, temperature, tools
        self.calls.append(messages)
        system_prompt = messages[0]["content"]
        identity = "研究助手" if "Research Agent" in system_prompt else "写作助手"
        yield ProviderTurnEvent(kind="text_delta", content=identity)
        yield ProviderTurnEvent(kind="text_delta", content="已收到")


class SlowRuntimeClient:
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
        del model, messages, temperature, tools
        yield ProviderTurnEvent(kind="text_delta", content="部分回答")
        await asyncio.Event().wait()


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def provider_payload() -> dict[str, object]:
    return {
        "name": "Runtime Provider",
        "base_url": "https://example.com/v1",
        "api_key": "sk-runtime-test",
        "models": [{"model_name": "runtime-model"}],
    }


def wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach a terminal state")


def wait_for_output(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["output_text"]:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not stream output")


def create_agent(
    client: TestClient,
    *,
    provider_id: str,
    model_id: str,
    name: str,
    description: str,
) -> dict[str, object]:
    response = client.post(
        "/api/agents",
        json={
            "name": name,
            "description": description,
            "provider_id": provider_id,
            "model_id": model_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_runtime_persists_history_and_replays_sse(tmp_path: Path) -> None:
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
    RecordingRuntimeClient.calls = []

    with TestClient(application) as client:
        application.state.provider_client_factory = RecordingRuntimeClient
        provider = client.post("/api/providers", json=provider_payload()).json()
        provider_id = provider["id"]
        model_id = provider["models"][0]["id"]
        research_agent = create_agent(
            client,
            provider_id=provider_id,
            model_id=model_id,
            name="Research Agent",
            description="只负责严谨研究",
        )
        writing_agent = create_agent(
            client,
            provider_id=provider_id,
            model_id=model_id,
            name="Writing Agent",
            description="只负责故事写作",
        )
        research_chat = client.post(
            "/api/chats", json={"agent_id": research_agent["id"]}
        ).json()
        assert research_chat["channel"] == "console"
        assert research_chat["channel_id"] is None
        assert research_chat["channel_name"] is None
        assert research_chat["external_user_id"] is None
        writing_chat = client.post(
            "/api/chats", json={"agent_id": writing_agent["id"]}
        ).json()

        first_run_response = client.post(
            f"/api/chats/{research_chat['id']}/runs",
            json={"content": "分析这个问题"},
        )
        assert first_run_response.status_code == 202
        first_run = wait_for_terminal(client, first_run_response.json()["id"])
        assert first_run["status"] == "completed"
        assert first_run["output_text"] == "研究助手已收到"

        with client.stream(
            "GET", f"/api/runs/{first_run['id']}/events"
        ) as event_response:
            event_body = event_response.read().decode("utf-8")
        assert event_response.status_code == 200
        assert "id: 1" in event_body
        assert "event: run.started" in event_body
        assert "event: run.delta" in event_body
        assert "event: run.completed" in event_body

        second_run_response = client.post(
            f"/api/chats/{research_chat['id']}/runs",
            json={"content": "结合上一轮继续"},
        )
        second_run = wait_for_terminal(client, second_run_response.json()["id"])
        assert second_run["status"] == "completed"
        second_call = RecordingRuntimeClient.calls[-1]
        assert [message["role"] for message in second_call] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert second_call[-2]["content"] == "研究助手已收到"

        writing_run_response = client.post(
            f"/api/chats/{writing_chat['id']}/runs",
            json={"content": "写一个开头"},
        )
        writing_run = wait_for_terminal(client, writing_run_response.json()["id"])
        assert writing_run["output_text"] == "写作助手已收到"
        assert "Research Agent" in RecordingRuntimeClient.calls[0][0]["content"]
        assert "Writing Agent" in RecordingRuntimeClient.calls[-1][0]["content"]

        detail = client.get(f"/api/chats/{research_chat['id']}").json()
        assert [message["role"] for message in detail["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert all(message["status"] == "final" for message in detail["messages"])
        assert client.delete(f"/api/agents/{research_agent['id']}").status_code == 409

    restarted_application = create_app(settings)
    with TestClient(restarted_application) as restarted_client:
        persisted = restarted_client.get(f"/api/chats/{research_chat['id']}")
        assert persisted.status_code == 200
        assert len(persisted.json()["messages"]) == 4


def test_cancel_stops_active_run_and_keeps_partial_answer(tmp_path: Path) -> None:
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
        application.state.provider_client_factory = SlowRuntimeClient
        provider = client.post("/api/providers", json=provider_payload()).json()
        agent = create_agent(
            client,
            provider_id=provider["id"],
            model_id=provider["models"][0]["id"],
            name="Slow Agent",
            description="用于取消测试",
        )
        chat = client.post("/api/chats", json={"agent_id": agent["id"]}).json()
        run_response = client.post(
            f"/api/chats/{chat['id']}/runs", json={"content": "开始慢速回答"}
        )
        run_id = run_response.json()["id"]
        streamed = wait_for_output(client, run_id)
        assert streamed["status"] == "running"

        concurrent = client.post(
            f"/api/chats/{chat['id']}/runs", json={"content": "并发请求"}
        )
        assert concurrent.status_code == 409

        cancel_response = client.post(f"/api/runs/{run_id}/cancel")
        assert cancel_response.status_code == 200
        cancelled = wait_for_terminal(client, run_id)
        assert cancelled["status"] == "cancelled"
        assert cancelled["output_text"] == "部分回答"

        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert detail["messages"][-1]["role"] == "assistant"
        assert detail["messages"][-1]["status"] == "partial"
        assert detail["messages"][-1]["content"] == "部分回答"

        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            event_body = response.read().decode("utf-8")
        assert "event: run.cancelled" in event_body
