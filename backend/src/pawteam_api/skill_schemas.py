"""Validation contracts for Agent-specific SKILL.md packages."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)
    enabled: bool = True
    channel_scope: list[Literal["console"]] = Field(
        default_factory=lambda: ["console"], min_length=1
    )
    config: dict[str, object] = Field(default_factory=dict)

    @field_validator("name", "description", "content")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Skill text fields cannot be empty")
        return normalized

    @field_validator("channel_scope")
    @classmethod
    def unique_channels(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Channel scope must not contain duplicates")
        return value


class SkillUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    enabled: bool | None = None
    channel_scope: list[Literal["console"]] | None = Field(default=None, min_length=1)
    config: dict[str, object] | None = None

    @field_validator("description", "content")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Skill text fields cannot be empty")
        return normalized

    @field_validator("channel_scope")
    @classmethod
    def unique_optional_channels(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Channel scope must not contain duplicates")
        return value


class SkillResponse(BaseModel):
    id: str
    agent_id: str
    name: str
    description: str
    path: str
    content: str
    enabled: bool
    channel_scope: list[str]
    config: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime
