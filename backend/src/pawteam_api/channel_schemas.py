"""API contracts for external messaging Channels."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeComChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=36)
    corp_id: str = Field(min_length=1, max_length=100)
    wecom_agent_id: int = Field(gt=0)
    token: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    encoding_aes_key: str = Field(
        min_length=43, max_length=43, pattern=r"^[A-Za-z0-9]+$"
    )
    corp_secret: str = Field(min_length=1, max_length=500)

    @field_validator("name", "corp_id", "corp_secret")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class WeComChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=36)
    corp_id: str = Field(min_length=1, max_length=100)
    wecom_agent_id: int = Field(gt=0)


class WeComSecretRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    token: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    encoding_aes_key: str = Field(
        min_length=43, max_length=43, pattern=r"^[A-Za-z0-9]+$"
    )
    corp_secret: str = Field(min_length=1, max_length=500)


class ChannelStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    status: Literal["active", "disabled"]


class ChannelResponse(BaseModel):
    id: str
    name: str
    kind: Literal["wecom"]
    agent_id: str
    agent_name: str
    status: Literal["active", "disabled"]
    corp_id: str
    wecom_agent_id: int
    callback_path: str
    has_secrets: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ChannelMessageResponse(BaseModel):
    id: str
    channel_id: str
    external_conversation_id: str
    external_user_id: str
    external_message_id: str
    direction: Literal["inbound", "outbound"]
    content: str
    status: str
    chat_session_id: str
    run_id: str | None
    attempts: int
    error_message: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DebugInboundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_user_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    external_conversation_id: str | None = Field(default=None, max_length=200)
    external_message_id: str | None = Field(default=None, max_length=200)


class ChannelIngressResponse(BaseModel):
    duplicate: bool
    channel_message_id: str
    chat_session_id: str
    run_id: str | None
    outbound_message_id: str | None
