"""API contracts for Team configuration and Agent delegation audits."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AgentId = Annotated[str, Field(min_length=1, max_length=36)]


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    coordinator_agent_id: AgentId
    member_agent_ids: list[AgentId] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Team name cannot be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("member_agent_ids")
    @classmethod
    def unique_members(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Team members must not contain duplicates")
        return value

    @model_validator(mode="after")
    def coordinator_is_not_worker(self) -> "TeamCreate":
        if self.coordinator_agent_id in self.member_agent_ids:
            raise ValueError("Coordinator must not also appear in member_agent_ids")
        return self


class TeamUpdate(TeamCreate):
    expected_version: int = Field(ge=1)


class TeamMemberResponse(BaseModel):
    agent_id: str
    agent_name: str
    role: Literal["coordinator", "member"]
    agent_status: Literal["active", "disabled"]


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str
    coordinator_agent_id: str
    coordinator_agent_name: str
    status: Literal["active", "disabled"]
    members: list[TeamMemberResponse]
    version: int
    created_at: datetime
    updated_at: datetime


class DelegationResponse(BaseModel):
    id: str
    parent_run_id: str
    child_run_id: str
    team_id: str
    team_name: str
    source_agent_id: str
    source_agent_name: str
    target_agent_id: str
    target_agent_name: str
    task: str
    status: Literal["requested", "running", "completed", "failed", "cancelled"]
    result_text: str
    error_message: str | None
    depth: int
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
