import asyncio
import base64
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pawteam_api.channels.wecom_client import WeComAccessToken
from pawteam_api.channels.wecom_crypto import WeComCrypto
from pawteam_api.channels.wecom_qr import WeComBotCredentials
from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base
from pawteam_api.providers.client import ProviderTurnEvent


class ChannelRuntimeClient:
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
        assert messages[-1]["content"] == "帮我总结今天的工作"
        yield ProviderTurnEvent(kind="text_delta", content="今天完成了企业微信接入。")


class FakeWeComClient:
    token_requests: list[tuple[str, str]] = []
    sent: list[dict[str, object]] = []

    def __init__(self, timeout_seconds: float) -> None:
        del timeout_seconds

    async def access_token(self, corp_id: str, corp_secret: str) -> WeComAccessToken:
        self.token_requests.append((corp_id, corp_secret))
        return WeComAccessToken("test-access-token", 7200)

    async def send_text(
        self,
        *,
        access_token: str,
        user_id: str,
        agent_id: int,
        content: str,
    ) -> None:
        self.sent.append(
            {
                "access_token": access_token,
                "user_id": user_id,
                "agent_id": agent_id,
                "content": content,
            }
        )


class FakeBotConnection:
    instances: list["FakeBotConnection"] = []

    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        max_reconnect_attempts: int,
        on_message: Any,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.max_reconnect_attempts = max_reconnect_attempts
        self.on_message = on_message
        self.status = "stopped"
        self.loop: asyncio.AbstractEventLoop | None = None
        self.sent: list[tuple[str, str]] = []
        self.instances.append(self)

    def start(self, main_loop: asyncio.AbstractEventLoop) -> None:
        self.loop = main_loop
        self.status = "connected"

    async def stop(self) -> None:
        self.status = "stopped"

    async def send_text(self, chat_id: str, content: str) -> None:
        self.sent.append((chat_id, content))

    def emit(self, frame: dict[str, object]) -> None:
        assert self.loop is not None
        future = asyncio.run_coroutine_threadsafe(self.on_message(frame), self.loop)
        future.result(timeout=2)


class FakeQrAuthorization:
    def __init__(self) -> None:
        self.ready = False

    async def start(self) -> tuple[str, str, int]:
        return "opaque-auth-session-1234567890", "data:image/png;base64,dGVzdA==", 300

    async def poll(self, session_id: str) -> tuple[str, str | None]:
        assert session_id == "opaque-auth-session-1234567890"
        self.ready = True
        return "ready", None

    def consume(self, session_id: str) -> WeComBotCredentials:
        assert self.ready is True
        assert session_id == "opaque-auth-session-1234567890"
        return WeComBotCredentials("bot-id-should-not-leak", "bot-secret-encrypted")


async def create_test_schema(settings: Settings) -> None:
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def wait_for_delivery(client: TestClient, channel_id: str) -> list[dict[str, object]]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        messages = client.get(f"/api/channels/{channel_id}/messages").json()
        outbound = [item for item in messages if item["direction"] == "outbound"]
        if outbound and outbound[0]["status"] == "delivered":
            return messages
        time.sleep(0.01)
    raise AssertionError("Channel response was not delivered")


def test_encrypted_wecom_callback_creates_one_run_and_active_reply(
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
    FakeWeComClient.sent = []
    FakeWeComClient.token_requests = []

    with TestClient(application) as client:
        application.state.provider_client_factory = ChannelRuntimeClient
        application.state.wecom_client_factory = FakeWeComClient
        provider = client.post(
            "/api/providers",
            json={
                "name": "Channel Provider",
                "base_url": "https://example.com/v1",
                "api_key": "sk-channel-test",
                "models": [{"model_name": "channel-model"}],
            },
        ).json()
        agent = client.post(
            "/api/agents",
            json={
                "name": "企业微信助理",
                "description": "通过企业微信回答工作问题",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
                "is_coordinator": False,
            },
        ).json()
        aes_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()[:-1]
        created = client.post(
            "/api/channels",
            json={
                "name": "内部工作助理",
                "agent_id": agent["id"],
                "corp_id": "ww-test-corp",
                "wecom_agent_id": 1000002,
                "token": "CallbackToken123",
                "encoding_aes_key": aes_key,
                "corp_secret": "wecom-corp-secret",
            },
        )
        assert created.status_code == 201
        channel = created.json()
        assert channel["has_secrets"] is True
        assert "token" not in channel
        assert "corp_secret" not in channel

        encrypted_secret = next((tmp_path / "secrets").glob("channel_*.secret"))
        stored_bytes = encrypted_secret.read_bytes()
        assert b"wecom-corp-secret" not in stored_bytes
        assert b"CallbackToken123" not in stored_bytes

        crypto = WeComCrypto("CallbackToken123", aes_key, "ww-test-corp")
        timestamp = str(int(time.time()))
        nonce = "918273"
        echo = crypto.encrypt(b"verify-ok", random_bytes=b"v" * 16)
        signature = crypto.signature(timestamp, nonce, echo)
        verified = client.get(
            channel["callback_path"],
            params={
                "msg_signature": signature,
                "timestamp": timestamp,
                "nonce": nonce,
                "echostr": echo,
            },
        )
        assert verified.status_code == 200
        assert verified.text == "verify-ok"

        plaintext = (
            "<xml><ToUserName><![CDATA[ww-test-corp]]></ToUserName>"
            "<FromUserName><![CDATA[zhangsan]]></FromUserName>"
            f"<CreateTime>{timestamp}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[帮我总结今天的工作]]></Content>"
            "<MsgId>7788990011</MsgId></xml>"
        ).encode()
        encrypted = crypto.encrypt(plaintext, random_bytes=b"m" * 16)
        callback_signature = crypto.signature(timestamp, nonce, encrypted)
        callback_body = (
            f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
        ).encode()
        params = {
            "msg_signature": callback_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }
        accepted = client.post(
            channel["callback_path"], params=params, content=callback_body
        )
        assert accepted.status_code == 200
        assert accepted.text == "success"

        messages = wait_for_delivery(client, channel["id"])
        assert len(messages) == 2
        inbound = next(item for item in messages if item["direction"] == "inbound")
        outbound = next(item for item in messages if item["direction"] == "outbound")
        assert inbound["status"] == "completed"
        assert outbound["content"] == "今天完成了企业微信接入。"
        assert outbound["attempts"] == 1
        assert FakeWeComClient.token_requests == [("ww-test-corp", "wecom-corp-secret")]
        assert FakeWeComClient.sent == [
            {
                "access_token": "test-access-token",
                "user_id": "zhangsan",
                "agent_id": 1000002,
                "content": "今天完成了企业微信接入。",
            }
        ]

        duplicate = client.post(
            channel["callback_path"], params=params, content=callback_body
        )
        assert duplicate.status_code == 200
        assert len(client.get(f"/api/channels/{channel['id']}/messages").json()) == 2
        chats = client.get("/api/chats").json()
        assert len(chats) == 1
        assert chats[0]["channel"] == "wecom"
        assert chats[0]["channel_id"] == channel["id"]
        assert chats[0]["channel_name"] == "内部工作助理"
        assert chats[0]["channel_kind"] == "wecom"
        assert chats[0]["external_conversation_id"] == "zhangsan"
        assert chats[0]["external_user_id"] == "zhangsan"

        invalid = client.post(
            channel["callback_path"],
            params={**params, "msg_signature": "0" * 40},
            content=callback_body,
        )
        assert invalid.status_code == 401


def test_channel_debug_ingress_and_optimistic_configuration(tmp_path: Path) -> None:
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
        provider = client.post(
            "/api/providers",
            json={
                "name": "P",
                "base_url": "https://example.com/v1",
                "api_key": "sk-test",
                "models": [{"model_name": "m"}],
            },
        ).json()
        agent = client.post(
            "/api/agents",
            json={
                "name": "A",
                "description": "A",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
                "is_coordinator": False,
            },
        ).json()
        aes_key = base64.b64encode(b"a" * 32).decode()[:-1]
        channel = client.post(
            "/api/channels",
            json={
                "name": "C",
                "agent_id": agent["id"],
                "corp_id": "ww-corp",
                "wecom_agent_id": 1,
                "token": "Token1",
                "encoding_aes_key": aes_key,
                "corp_secret": "secret",
            },
        ).json()
        stale = client.put(
            f"/api/channels/{channel['id']}/status",
            json={"expected_version": 99, "status": "disabled"},
        )
        assert stale.status_code == 409
        disabled = client.put(
            f"/api/channels/{channel['id']}/status",
            json={"expected_version": 1, "status": "disabled"},
        )
        assert disabled.status_code == 200
        debug = client.post(
            f"/api/channels/{channel['id']}/debug-inbound",
            json={"external_user_id": "dev-user", "content": "hello"},
        )
        assert debug.status_code == 409
        deleted = client.delete(f"/api/channels/{channel['id']}")
        assert deleted.status_code == 204


def test_wecom_bot_qr_connects_receives_and_replies_without_exposing_secret(
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
    FakeBotConnection.instances = []

    with TestClient(application) as client:
        application.state.provider_client_factory = ChannelRuntimeClient
        application.state.wecom_bot_connection_factory = FakeBotConnection
        application.state.wecom_qr_service = FakeQrAuthorization()
        provider = client.post(
            "/api/providers",
            json={
                "name": "Bot Provider",
                "base_url": "https://example.com/v1",
                "api_key": "sk-bot-test",
                "models": [{"model_name": "bot-model"}],
            },
        ).json()
        agent = client.post(
            "/api/agents",
            json={
                "name": "智能机器人助理",
                "description": "通过智能机器人长连接回复",
                "provider_id": provider["id"],
                "model_id": provider["models"][0]["id"],
                "is_coordinator": False,
            },
        ).json()

        started = client.post("/api/channels/wecom-bot/qrcode")
        assert started.status_code == 200
        qr_body = started.json()
        assert qr_body == {
            "auth_session_id": "opaque-auth-session-1234567890",
            "qrcode_image": "data:image/png;base64,dGVzdA==",
            "expires_in": 300,
        }
        assert "secret" not in started.text.lower()
        polled = client.get(
            f"/api/channels/wecom-bot/qrcode/{qr_body['auth_session_id']}"
        )
        assert polled.json() == {"status": "ready", "message": None}
        assert "bot-id" not in polled.text

        created = client.post(
            "/api/channels/wecom-bot",
            json={
                "name": "扫码机器人",
                "agent_id": agent["id"],
                "auth_session_id": qr_body["auth_session_id"],
            },
        )
        assert created.status_code == 201
        channel = created.json()
        assert channel["kind"] == "wecom_bot"
        assert channel["connection_status"] == "connected"
        assert channel["bot_id_masked"] == "bot-id-***leak"
        assert "bot-secret" not in created.text
        assert len(FakeBotConnection.instances) == 1
        connection = FakeBotConnection.instances[0]
        assert connection.bot_id == "bot-id-should-not-leak"
        assert connection.secret == "bot-secret-encrypted"

        encrypted_secret = next((tmp_path / "secrets").glob("channel_*.secret"))
        assert b"bot-secret-encrypted" not in encrypted_secret.read_bytes()
        connection.emit(
            {
                "body": {
                    "msgtype": "text",
                    "msgid": "wecom-bot-message-1",
                    "chatid": "group-chat-100",
                    "from": {"userid": "zhangsan"},
                    "text": {"content": "帮我总结今天的工作"},
                }
            }
        )
        messages = wait_for_delivery(client, channel["id"])
        assert len(messages) == 2
        assert connection.sent == [
            ("group-chat-100", "今天完成了企业微信接入。")
        ]
        chats = client.get("/api/chats").json()
        assert len(chats) == 1
        assert chats[0]["channel"] == "wecom"
        assert chats[0]["channel_id"] == channel["id"]
        assert chats[0]["channel_name"] == "扫码机器人"
        assert chats[0]["channel_kind"] == "wecom_bot"
        assert chats[0]["external_conversation_id"] == "group-chat-100"
        assert chats[0]["external_user_id"] == "zhangsan"
        detail = client.get(f"/api/chats/{chats[0]['id']}").json()
        assert [item["content"] for item in detail["messages"]] == [
            "帮我总结今天的工作",
            "今天完成了企业微信接入。",
        ]
        forged_web_message = client.post(
            f"/api/chats/{chats[0]['id']}/runs",
            json={"content": "这条消息不应伪装成企业微信用户"},
        )
        assert forged_web_message.status_code == 409
        assert "read-only" in forged_web_message.json()["detail"]

        disabled = client.put(
            f"/api/channels/{channel['id']}/status",
            json={"expected_version": 1, "status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["connection_status"] == "stopped"
        assert connection.status == "stopped"
