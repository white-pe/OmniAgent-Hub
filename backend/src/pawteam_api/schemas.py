"""Public API schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    name: str
    version: str
    environment: str
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
