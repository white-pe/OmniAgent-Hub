import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base


class FakeProviderClient:
    last_api_key: str | None = None

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        FakeProviderClient.last_api_key = api_key

    async def test(self, model: str) -> str:
        return f"OK from {model}"

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
    ) -> AsyncIterator[str]:
        del model, prompt, system_prompt, temperature
        for content in ("你", "好"):
            yield content


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def test_provider_lifecycle_keeps_api_key_out_of_database_response(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "test.db"
    secrets_path = tmp_path / "secrets"
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=secrets_path,
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)

    with TestClient(application) as client:
        application.state.provider_client_factory = FakeProviderClient
        create_response = client.post(
            "/api/providers",
            json={
                "name": "Qwen Test",
                "base_url": "https://example.com/v1/",
                "api_key": "sk-not-plaintext",
                "models": [{"model_name": "qwen-plus"}],
            },
        )
        assert create_response.status_code == 201
        provider = create_response.json()
        provider_id = provider["id"]
        model_id = provider["models"][0]["id"]
        assert provider["base_url"] == "https://example.com/v1"
        assert provider["configured"] is True
        assert "api_key" not in provider
        assert "api_key_ref" not in provider

        update_response = client.put(
            f"/api/providers/{provider_id}",
            json={
                "name": "Qwen Test Updated",
                "base_url": "https://updated.example.com/v1/",
                "api_key": "sk-rotated",
                "models": [
                    {"model_name": "qwen-plus", "display_name": "Qwen Plus"},
                    {"model_name": "qwen-max"},
                ],
            },
        )
        assert update_response.status_code == 200
        provider = update_response.json()
        assert provider["name"] == "Qwen Test Updated"
        assert provider["base_url"] == "https://updated.example.com/v1"
        assert provider["models"][0]["id"] == model_id
        assert [item["model_name"] for item in provider["models"]] == [
            "qwen-plus",
            "qwen-max",
        ]

        list_response = client.get("/api/providers")
        assert list_response.status_code == 200
        assert list_response.json() == [provider]

        secret_files = list(secrets_path.glob("*.secret"))
        assert len(secret_files) == 1
        assert b"sk-not-plaintext" not in secret_files[0].read_bytes()
        assert b"sk-not-plaintext" not in database_path.read_bytes()

        test_response = client.post(
            f"/api/providers/{provider_id}/test", json={"model_id": model_id}
        )
        assert test_response.status_code == 200
        assert test_response.json()["reply_preview"] == "OK from qwen-plus"
        assert FakeProviderClient.last_api_key == "sk-rotated"

        with client.stream(
            "POST",
            f"/api/providers/{provider_id}/chat/stream",
            json={"model_id": model_id, "prompt": "你好"},
        ) as stream_response:
            stream_body = stream_response.read().decode("utf-8")
        assert stream_response.status_code == 200
        assert "event: start" in stream_body
        assert 'data: {"content": "你"}' in stream_body
        assert 'data: {"content": "好"}' in stream_body
        assert "event: done" in stream_body

        delete_response = client.delete(f"/api/providers/{provider_id}")
        assert delete_response.status_code == 204
        assert list(secrets_path.glob("*.secret")) == []
        assert client.get(f"/api/providers/{provider_id}").status_code == 404


def test_duplicate_provider_name_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    )
    asyncio.run(create_test_schema(settings))
    application = create_app(settings)
    payload = {
        "name": "Unique Provider",
        "base_url": "https://example.com/v1",
        "api_key": "sk-test",
        "models": [{"model_name": "test-model"}],
    }

    with TestClient(application) as client:
        assert client.post("/api/providers", json=payload).status_code == 201
        duplicate_response = client.post("/api/providers", json=payload)

    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Provider name already exists"
