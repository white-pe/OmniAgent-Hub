"""Strict contracts for generated, reviewable Agent Blueprints."""

from datetime import datetime
from re import fullmatch
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_BLUEPRINT_TOOLS = (
    "read_workspace_file",
    "search_workspace_files",
    "delegate_to_agent",
)
MODEL_HINTS = ("fast", "balanced", "reasoning")


class AgentBlueprint(BaseModel):
    """Untrusted model output after strict structural and policy validation."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    role: str = Field(min_length=1, max_length=500)
    goals: list[str] = Field(min_length=1, max_length=8)
    tone: str = Field(min_length=1, max_length=300)
    rules: list[str] = Field(min_length=1, max_length=12)
    requested_tools: list[str] = Field(default_factory=list, max_length=8)
    requested_skills: list[str] = Field(default_factory=list, max_length=8)
    model_hint: Literal["fast", "balanced", "reasoning"] = "balanced"
    is_coordinator: bool = False

    @field_validator("name", "description", "role", "tone")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Text fields cannot be empty")
        return normalized

    @field_validator("goals", "rules")
    @classmethod
    def normalize_lines(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("At least one non-empty item is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("List items must not be duplicated")
        return normalized

    @field_validator("requested_tools")
    @classmethod
    def validate_tools(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        unsupported = sorted(set(normalized).difference(ALLOWED_BLUEPRINT_TOOLS))
        if unsupported:
            raise ValueError(f"Unsupported tools: {', '.join(unsupported)}")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Requested tools must not be duplicated")
        return normalized

    @field_validator("requested_skills")
    @classmethod
    def validate_skill_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        invalid = [
            value
            for value in normalized
            if not fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value)
        ]
        if invalid:
            raise ValueError("Skill IDs may contain lowercase letters, digits, - and _")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Requested skills must not be duplicated")
        return normalized

    @model_validator(mode="after")
    def validate_delegation_policy(self) -> "AgentBlueprint":
        if "delegate_to_agent" in self.requested_tools and not self.is_coordinator:
            raise ValueError("Only a coordinator Agent may request delegate_to_agent")
        return self


class BlueprintGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=10, max_length=4000)
    provider_id: str = Field(min_length=1, max_length=36)
    model_id: str = Field(min_length=1, max_length=36)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("Please describe the Agent in at least 10 characters")
        return normalized


class BlueprintApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=36)
    blueprint: AgentBlueprint
    provider_id: str = Field(min_length=1, max_length=36)
    model_id: str = Field(min_length=1, max_length=36)


class BlueprintDraftResponse(BaseModel):
    draft_id: str
    request_text: str
    blueprint: AgentBlueprint
    warnings: list[str]
    status: Literal["draft", "cancelled", "applied", "expired"]
    source_provider_id: str
    source_provider_name: str
    source_model_id: str
    source_model_name: str
    applied_agent_id: str | None
    created_at: datetime
    expires_at: datetime
