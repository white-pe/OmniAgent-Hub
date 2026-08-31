"""Validation contracts for Agent metadata and Workspace files."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    provider_id: str = Field(min_length=1, max_length=36)
    model_id: str = Field(min_length=1, max_length=36)
    is_coordinator: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Agent name cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class AgentUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    provider_id: str | None = Field(default=None, min_length=1, max_length=36)
    model_id: str | None = Field(default=None, min_length=1, max_length=36)
    is_coordinator: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Agent name cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    status: Literal["active", "disabled"]
    workspace_path: str
    provider_id: str
    provider_name: str
    model_id: str
    model_name: str
    is_coordinator: bool
    version: int
    created_at: datetime
    updated_at: datetime


class WorkspaceFileResponse(BaseModel):
    agent_id: str
    filename: str
    content: str
    agent_version: int


class WorkspaceFileUpdate(BaseModel):
    content: str = Field(max_length=200_000)
    expected_version: int = Field(ge=1)
