"""API contracts for durable console chats and Agent Runs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChatStatus = Literal["active", "archived"]
RunStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]
MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["final", "partial"]


class ChatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=36)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ChatSessionResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    title: str
    channel: Literal["console"]
    status: ChatStatus
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: str
    session_id: str
    run_id: str | None
    role: MessageRole
    content: str
    status: MessageStatus
    sequence: int
    created_at: datetime


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty")
        return normalized


class RunResponse(BaseModel):
    id: str
    session_id: str
    agent_id: str
    provider_id: str
    model_id: str
    model_name: str
    status: RunStatus
    output_text: str
    error_message: str | None
    cancel_requested: bool
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ChatDetailResponse(BaseModel):
    session: ChatSessionResponse
    messages: list[MessageResponse]
    runs: list[RunResponse]
