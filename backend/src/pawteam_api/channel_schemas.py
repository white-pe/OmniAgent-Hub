"""API contracts for external messaging Channels."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class WeComBotChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=36)
    auth_session_id: str | None = Field(default=None, min_length=20, max_length=200)
    bot_id: str | None = Field(default=None, min_length=1, max_length=300)
    secret: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("name", "bot_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def one_credential_source(self) -> "WeComBotChannelCreate":
        uses_qr = self.auth_session_id is not None
        uses_manual = self.bot_id is not None or self.secret is not None
        if uses_qr == uses_manual:
            raise ValueError(
                "Use either auth_session_id or the complete Bot ID/Secret pair"
            )
        if uses_manual and (not self.bot_id or not self.secret):
            raise ValueError("Bot ID and Secret must be provided together")
        return self


class WeComBotChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=36)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class WeComBotCredentialsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    auth_session_id: str | None = Field(default=None, min_length=20, max_length=200)
    bot_id: str | None = Field(default=None, min_length=1, max_length=300)
    secret: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("bot_id")
    @classmethod
    def strip_bot_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def one_credential_source(self) -> "WeComBotCredentialsUpdate":
        uses_qr = self.auth_session_id is not None
        uses_manual = self.bot_id is not None or self.secret is not None
        if uses_qr == uses_manual:
            raise ValueError(
                "Use either auth_session_id or the complete Bot ID/Secret pair"
            )
        if uses_manual and (not self.bot_id or not self.secret):
            raise ValueError("Bot ID and Secret must be provided together")
        return self


class WeComQrStartResponse(BaseModel):
    auth_session_id: str
    qrcode_image: str
    expires_in: int


class WeComQrStatusResponse(BaseModel):
    status: Literal["waiting", "ready", "expired", "failed"]
    message: str | None = None


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
    kind: Literal["wecom", "wecom_bot"]
    agent_id: str
    agent_name: str
    status: Literal["active", "disabled"]
    corp_id: str | None = None
    wecom_agent_id: int | None = None
    bot_id_masked: str | None = None
    callback_path: str | None = None
    connection_status: Literal[
        "not_applicable", "stopped", "connecting", "connected", "error"
    ] = "not_applicable"
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
