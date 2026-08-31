"""Allowlisted, schema-validated Tools with a second server-side permission check."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pawteam_api.config import Settings
from pawteam_api.workspaces.store import WorkspaceError, WorkspaceStore


class GetCurrentTimeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="UTC", min_length=1, max_length=100)


class ReadWorkspaceFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class ToolContext:
    agent_id: str
    run_id: str
    workspace_path: str
    channel: str


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    arguments: dict[str, object]
    payload: dict[str, object]
    error_message: str | None = None


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[dict[str, object]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(
        self,
        settings: Settings,
        workspace_store: WorkspaceStore,
    ) -> None:
        self.settings = settings
        self.workspace_store = workspace_store
        self._definitions = {
            "get_current_time": ToolDefinition(
                name="get_current_time",
                description="Get the current date and time in one IANA timezone.",
                arguments_model=GetCurrentTimeArguments,
                handler=self._get_current_time,
            ),
            "read_workspace_file": ToolDefinition(
                name="read_workspace_file",
                description=(
                    "Read one UTF-8 text file inside this Agent's own Workspace. "
                    "The path must be relative and cannot escape the Workspace."
                ),
                arguments_model=ReadWorkspaceFileArguments,
                handler=self._read_workspace_file,
            ),
        }

    def definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def contains(self, name: str) -> bool:
        return name in self._definitions

    def openai_definitions(self, enabled_names: set[str]) -> list[dict[str, object]]:
        return [
            definition.openai_schema()
            for definition in self._definitions.values()
            if definition.name in enabled_names
        ]

    async def execute(
        self,
        *,
        name: str,
        raw_arguments: str,
        enabled_names: set[str],
        context: ToolContext,
    ) -> ToolExecutionResult:
        definition = self._definitions.get(name)
        if definition is None:
            return self._rejected({}, f'Unknown Tool "{name}"')
        if name not in enabled_names:
            return self._rejected({}, f'Tool "{name}" is not enabled for this Agent')

        try:
            decoded = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return self._rejected({}, "Tool arguments are not valid JSON")
        if not isinstance(decoded, dict):
            return self._rejected({}, "Tool arguments must be a JSON object")

        arguments = {str(key): value for key, value in decoded.items()}
        try:
            validated = definition.arguments_model.model_validate(arguments)
        except ValidationError as error:
            message = error.errors(include_url=False)[0]["msg"]
            return self._rejected(arguments, f"Invalid Tool arguments: {message}")

        try:
            async with asyncio.timeout(self.settings.tool_timeout_seconds):
                data = await definition.handler(validated, context)
            payload = self._bounded_payload({"ok": True, "data": data})
            return ToolExecutionResult(
                status="completed",
                arguments=arguments,
                payload=payload,
            )
        except TimeoutError:
            return self._failed(arguments, "Tool execution timed out")
        except (WorkspaceError, ZoneInfoNotFoundError, ValueError) as error:
            return self._failed(arguments, str(error))
        except Exception:
            return self._failed(arguments, "Tool execution failed unexpectedly")

    async def _get_current_time(
        self,
        arguments: BaseModel,
        _context: ToolContext,
    ) -> dict[str, object]:
        timezone = str(arguments.timezone)
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ZoneInfoNotFoundError(f'Unknown timezone "{timezone}"') from exc
        now = datetime.now(UTC).astimezone(zone)
        return {
            "timezone": timezone,
            "iso8601": now.isoformat(),
            "unix_timestamp": round(now.timestamp()),
        }

    async def _read_workspace_file(
        self,
        arguments: BaseModel,
        context: ToolContext,
    ) -> dict[str, object]:
        path = str(arguments.path)
        content = await asyncio.to_thread(
            self.workspace_store.read_relative,
            context.workspace_path,
            path,
        )
        return {"path": path, "content": content}

    def _bounded_payload(self, payload: dict[str, object]) -> dict[str, object]:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if len(serialized) <= self.settings.tool_result_max_chars:
            return payload
        return {
            "ok": True,
            "truncated": True,
            "content": serialized[: self.settings.tool_result_max_chars],
        }

    @staticmethod
    def _rejected(
        arguments: dict[str, object],
        message: str,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            status="rejected",
            arguments=arguments,
            payload={"ok": False, "error": message, "status": "rejected"},
            error_message=message,
        )

    @staticmethod
    def _failed(
        arguments: dict[str, object],
        message: str,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            status="failed",
            arguments=arguments,
            payload={"ok": False, "error": message, "status": "failed"},
            error_message=message,
        )
