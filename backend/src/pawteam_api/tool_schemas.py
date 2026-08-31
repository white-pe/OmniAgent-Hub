"""API contracts for Tool assignments and durable Tool call audits."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ToolCallStatus = Literal["requested", "running", "completed", "failed", "rejected"]


class ToolAssignmentResponse(BaseModel):
    name: str
    description: str
    enabled: bool
    input_schema: dict[str, object]


class ToolCallResponse(BaseModel):
    id: str
    run_id: str
    provider_call_id: str
    tool_name: str
    arguments: dict[str, object]
    status: ToolCallStatus
    result: dict[str, object] | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
