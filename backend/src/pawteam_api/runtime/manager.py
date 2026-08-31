"""Background Agent execution with durable state and replayable events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.config import Settings
from pawteam_api.models import (
    Agent,
    AgentRun,
    AgentTool,
    ChannelMessage,
    ChatSession,
    Delegation,
    ExternalConversation,
    Message,
    ProviderModel,
    RunEvent,
    Skill,
    Team,
    TeamMember,
    ToolCall,
)
from pawteam_api.providers.client import ProviderRequestError, ProviderTurnEvent
from pawteam_api.providers.service import (
    ProviderConflictError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
    ProviderService,
)
from pawteam_api.runtime.prompt_builder import PromptBuilder
from pawteam_api.runtime.service import TERMINAL_RUN_STATUSES
from pawteam_api.security.secret_store import SecretNotFoundError, SecretStore
from pawteam_api.teams.runtime import (
    DelegateArguments,
    DelegationMember,
    DelegationTeam,
    delegation_tool_definition,
    team_prompt_section,
)
from pawteam_api.tools.registry import (
    ToolContext,
    ToolExecutionResult,
    ToolRegistry,
)
from pawteam_api.workspaces.store import WorkspaceError, WorkspaceStore

logger = logging.getLogger(__name__)


class RuntimeProviderClient(Protocol):
    def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        temperature: float,
        tools: list[dict[str, object]] | None,
    ) -> AsyncIterator[ProviderTurnEvent]: ...


ProviderClientFactory = Callable[[str, str, float], RuntimeProviderClient]


class ChannelDeliveryDispatcher(Protocol):
    def dispatch(self, message_id: str) -> None: ...


class RunCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedRun:
    client: RuntimeProviderClient
    model_name: str
    messages: list[dict[str, object]]
    agent_id: str
    workspace_path: str
    channel: str
    enabled_tools: set[str]
    tool_definitions: list[dict[str, object]]
    delegation_teams: tuple[DelegationTeam, ...]


@dataclass
class PendingToolCall:
    index: int
    call_id: str = ""
    name: str = ""
    arguments: str = ""


class RunManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        secret_store: SecretStore,
        workspace_store: WorkspaceStore,
        tool_registry: ToolRegistry,
        provider_client_factory: ProviderClientFactory,
        channel_dispatcher: ChannelDeliveryDispatcher | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.secret_store = secret_store
        self.workspace_store = workspace_store
        self.tool_registry = tool_registry
        self.provider_client_factory = provider_client_factory
        self.channel_dispatcher = channel_dispatcher
        self.prompt_builder = PromptBuilder(settings, workspace_store)
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, run_id: str) -> None:
        if run_id in self.tasks:
            return
        task = asyncio.create_task(self._execute(run_id), name=f"agent-run-{run_id}")
        self.tasks[run_id] = task
        task.add_done_callback(
            lambda completed, current_id=run_id: self.tasks.pop(current_id, None)
        )

    async def cancel(self, run_id: str) -> None:
        task = self.tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._finish_cancelled(run_id)

    async def recover_interrupted_runs(self) -> None:
        try:
            async with self.session_factory() as session:
                runs = (
                    await session.scalars(
                        select(AgentRun).where(
                            AgentRun.status.in_(("queued", "running", "cancelling"))
                        )
                    )
                ).all()
                interrupted = [
                    (run.id, run.status, run.cancel_requested) for run in runs
                ]
        except OperationalError as error:
            # Stage-zero health checks intentionally run before migrations.
            if "no such table: runs" not in str(error):
                raise
            return
        for run_id, run_status, cancel_requested in interrupted:
            if run_status == "cancelling" or cancel_requested:
                await self._finish_cancelled(run_id)
            else:
                await self._finish_failed(
                    run_id,
                    "Application restarted while the Run was active",
                )
        async with self.session_factory() as session:
            delegations = (
                await session.scalars(
                    select(Delegation).where(
                        Delegation.status.in_(("requested", "running"))
                    )
                )
            ).all()
            now = self._utc_now()
            for delegation in delegations:
                delegation.status = "failed"
                delegation.error_message = "Application restarted during delegation"
                delegation.finished_at = now
            await session.commit()

    async def shutdown(self) -> None:
        running = [task for task in self.tasks.values() if not task.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    async def _execute(self, run_id: str, *, propagate_cancel: bool = False) -> None:
        try:
            prepared = await self._prepare(run_id)
            if prepared is None:
                return
            received_content = False
            conversation = list(prepared.messages)
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                for _step in range(self.settings.runtime_max_steps):
                    turn_text = ""
                    pending_calls: dict[int, PendingToolCall] = {}
                    async for event in prepared.client.stream_turn(
                        model=prepared.model_name,
                        messages=conversation,
                        temperature=0.7,
                        tools=prepared.tool_definitions or None,
                    ):
                        if event.kind == "text_delta":
                            if not event.content:
                                continue
                            received_content = True
                            turn_text += event.content
                            await self._append_delta(run_id, event.content)
                            continue
                        call = pending_calls.setdefault(
                            event.index, PendingToolCall(index=event.index)
                        )
                        call.call_id += event.call_id
                        call.name += event.name
                        call.arguments += event.arguments

                    if not pending_calls:
                        if not turn_text:
                            raise ProviderRequestError(
                                "Provider returned no response content"
                            )
                        break

                    tool_calls = self._assistant_tool_calls(run_id, pending_calls)
                    conversation.append(
                        {
                            "role": "assistant",
                            "content": turn_text or None,
                            "tool_calls": tool_calls,
                        }
                    )
                    for pending, tool_call in zip(
                        sorted(pending_calls.values(), key=lambda item: item.index),
                        tool_calls,
                        strict=True,
                    ):
                        result = await self._execute_tool(
                            run_id=run_id,
                            pending=pending,
                            provider_call_id=str(tool_call["id"]),
                            prepared=prepared,
                        )
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": result,
                            }
                        )
                        await self._assert_run_active(run_id)
                else:
                    raise ProviderRequestError(
                        "Agent exceeded the maximum number of Tool steps"
                    )
            if not received_content:
                raise ProviderRequestError("Provider returned no response content")
            await self._finish_completed(run_id)
        except asyncio.CancelledError:
            await self._finish_cancelled(run_id)
            if propagate_cancel:
                raise
        except RunCancelledError:
            await self._finish_cancelled(run_id)
        except TimeoutError:
            await self._finish_failed(run_id, "Agent Run timed out")
        except (
            ProviderRequestError,
            ProviderNotFoundError,
            ProviderModelNotFoundError,
            ProviderConflictError,
            SecretNotFoundError,
            WorkspaceError,
        ) as error:
            await self._finish_failed(run_id, str(error))
        except Exception:
            logger.exception("Unexpected Agent Run failure", extra={"run_id": run_id})
            await self._finish_failed(run_id, "Agent Run failed unexpectedly")

    async def _prepare(self, run_id: str) -> PreparedRun | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AgentRun, ChatSession, Agent)
                    .join(ChatSession, ChatSession.id == AgentRun.session_id)
                    .join(Agent, Agent.id == AgentRun.agent_id)
                    .where(AgentRun.id == run_id)
                )
            ).one_or_none()
            if row is None:
                return None
            run, chat, agent = row
            if run.status not in ("queued", "cancelling"):
                return None
            if run.cancel_requested or run.status == "cancelling":
                raise RunCancelledError(run_id)
            if agent.status != "active":
                raise ProviderConflictError("Agent is disabled")

            runtime = await ProviderService(session, self.secret_store).runtime(
                run.provider_id, run.model_id
            )
            delegation = await session.scalar(
                select(Delegation).where(Delegation.child_run_id == run.id)
            )
            history = (
                []
                if delegation is not None
                else (
                    await session.scalars(
                        select(Message)
                        .where(Message.session_id == run.session_id)
                        .order_by(Message.sequence)
                    )
                ).all()
            )
            skills = (
                await session.scalars(
                    select(Skill)
                    .where(Skill.agent_id == agent.id, Skill.enabled.is_(True))
                    .order_by(Skill.created_at, Skill.name)
                )
            ).all()
            channel_skills = [
                skill for skill in skills if chat.channel in skill.channel_scope_json
            ]
            enabled_tools = {
                assignment.tool_name
                for assignment in (
                    await session.scalars(
                        select(AgentTool).where(
                            AgentTool.agent_id == agent.id,
                            AgentTool.enabled.is_(True),
                        )
                    )
                ).all()
                if self.tool_registry.contains(assignment.tool_name)
            }
            delegation_teams = await self._delegation_teams(session, agent)
            if delegation_teams:
                enabled_tools.add("delegate_to_agent")
            messages = self.prompt_builder.build(
                agent=agent,
                chat=chat,
                messages=list(history),
                skills=list(channel_skills),
                tool_names=enabled_tools,
                team_section=(
                    team_prompt_section(delegation_teams) if delegation_teams else None
                ),
            )
            if delegation is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你收到协调 Agent 委派的一项独立任务。只完成这项任务，"
                            "直接返回可供协调者使用的结果；不要假装拥有协调者的"
                            f"上下文或权限。\n\n任务：\n{delegation.task}"
                        ),
                    }
                )
            now = self._utc_now()
            run.status = "running"
            run.started_at = now
            await self._add_event(
                session,
                run.id,
                "run.started",
                {"run_id": run.id, "model": runtime.model_name},
            )
            await session.commit()
            client = self.provider_client_factory(
                runtime.base_url,
                runtime.api_key,
                self.settings.provider_timeout_seconds,
            )
            tool_definitions = self.tool_registry.openai_definitions(enabled_tools)
            if delegation_teams:
                tool_definitions.append(delegation_tool_definition(delegation_teams))
            return PreparedRun(
                client=client,
                model_name=runtime.model_name,
                messages=[dict(message) for message in messages],
                agent_id=agent.id,
                workspace_path=agent.workspace_path,
                channel=chat.channel,
                enabled_tools=enabled_tools,
                tool_definitions=tool_definitions,
                delegation_teams=delegation_teams,
            )

    async def _execute_tool(
        self,
        *,
        run_id: str,
        pending: PendingToolCall,
        provider_call_id: str,
        prepared: PreparedRun,
    ) -> str:
        tool_call_id = str(uuid4())
        requested_arguments = self._arguments_for_audit(pending.arguments)
        async with self.session_factory() as session:
            session.add(
                ToolCall(
                    id=tool_call_id,
                    run_id=run_id,
                    provider_call_id=provider_call_id,
                    tool_name=pending.name,
                    arguments_json=requested_arguments,
                    status="requested",
                )
            )
            await self._add_event(
                session,
                run_id,
                "tool.requested",
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": pending.name,
                    "arguments": requested_arguments,
                },
            )
            await session.commit()

        started_at = self._utc_now()
        async with self.session_factory() as session:
            tool_call = await session.get(ToolCall, tool_call_id)
            if tool_call is None:
                raise RuntimeError("Tool call audit record disappeared")
            tool_call.status = "running"
            tool_call.started_at = started_at
            await self._add_event(
                session,
                run_id,
                "tool.started",
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": pending.name,
                },
            )
            await session.commit()

        if pending.name == "delegate_to_agent":
            result = await self._execute_delegation(
                run_id=run_id,
                raw_arguments=pending.arguments,
                prepared=prepared,
            )
        else:
            result = await self.tool_registry.execute(
                name=pending.name,
                raw_arguments=pending.arguments,
                enabled_names=prepared.enabled_tools,
                context=ToolContext(
                    agent_id=prepared.agent_id,
                    run_id=run_id,
                    workspace_path=prepared.workspace_path,
                    channel=prepared.channel,
                ),
            )
        finished_at = self._utc_now()
        duration_ms = max(0, round((finished_at - started_at).total_seconds() * 1000))
        async with self.session_factory() as session:
            tool_call = await session.get(ToolCall, tool_call_id)
            if tool_call is None:
                raise RuntimeError("Tool call audit record disappeared")
            tool_call.arguments_json = result.arguments
            tool_call.status = result.status
            tool_call.result_json = result.payload
            tool_call.error_message = result.error_message
            tool_call.finished_at = finished_at
            tool_call.duration_ms = duration_ms
            event_type = f"tool.{result.status}"
            await self._add_event(
                session,
                run_id,
                event_type,
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": pending.name,
                    "status": result.status,
                    "duration_ms": duration_ms,
                    "result_preview": self._event_preview(result.payload),
                    **(
                        {"message": result.error_message}
                        if result.error_message is not None
                        else {}
                    ),
                },
            )
            await session.commit()
        return json.dumps(result.payload, ensure_ascii=False, default=str)

    async def _execute_delegation(
        self,
        *,
        run_id: str,
        raw_arguments: str,
        prepared: PreparedRun,
    ) -> ToolExecutionResult:
        try:
            arguments = DelegateArguments.model_validate_json(raw_arguments or "{}")
        except ValidationError as error:
            message = error.errors(include_url=False)[0]["msg"]
            return self._delegation_rejected(
                {}, f"Invalid delegation arguments: {message}"
            )
        argument_data = arguments.model_dump()
        if len(arguments.task) > self.settings.delegation_task_max_chars:
            return self._delegation_rejected(
                argument_data, "Delegation task exceeds the configured size limit"
            )
        team = next(
            (
                candidate
                for candidate in prepared.delegation_teams
                if candidate.team_id == arguments.team_id
            ),
            None,
        )
        if team is None:
            return self._delegation_rejected(
                argument_data, "Team is not active or not owned by this coordinator"
            )
        allowed_targets = {member.agent_id for member in team.members}
        if arguments.target_agent_id not in allowed_targets:
            return self._delegation_rejected(
                argument_data, "Target Agent is not an allowed member of this Team"
            )

        async with self.session_factory() as session:
            parent = await session.get(AgentRun, run_id)
            if parent is None:
                return self._delegation_rejected(argument_data, "Parent Run not found")
            active_team = await session.get(Team, arguments.team_id)
            source_agent = await session.get(Agent, parent.agent_id)
            membership = await session.scalar(
                select(TeamMember.id).where(
                    TeamMember.team_id == arguments.team_id,
                    TeamMember.agent_id == arguments.target_agent_id,
                    TeamMember.role == "member",
                )
            )
            if (
                active_team is None
                or active_team.status != "active"
                or active_team.coordinator_agent_id != parent.agent_id
                or source_agent is None
                or not source_agent.is_coordinator
                or membership is None
            ):
                return self._delegation_rejected(
                    argument_data,
                    "Team authorization changed before delegation execution",
                )
            root_run_id, ancestor_agents = await self._run_ancestry(session, parent)
            if arguments.target_agent_id in ancestor_agents:
                return self._delegation_rejected(
                    argument_data, "Delegation loop detected in the Run ancestry"
                )
            child_depth = parent.depth + 1
            if child_depth > self.settings.delegation_max_depth:
                return self._delegation_rejected(
                    argument_data, "Delegation depth limit exceeded"
                )
            call_count = await session.scalar(
                select(func.count(Delegation.id)).where(
                    Delegation.root_run_id == root_run_id
                )
            )
            if (call_count or 0) >= self.settings.delegation_max_calls_per_root:
                return self._delegation_rejected(
                    argument_data, "Delegation call budget exhausted"
                )
            target_row = (
                await session.execute(
                    select(Agent, ProviderModel.model_name)
                    .join(ProviderModel, ProviderModel.id == Agent.model_id)
                    .where(Agent.id == arguments.target_agent_id)
                )
            ).one_or_none()
            if target_row is None:
                return self._delegation_rejected(
                    argument_data, "Target Agent no longer exists"
                )
            target, model_name = target_row
            if target.status != "active":
                return self._delegation_rejected(
                    argument_data, "Target Agent is disabled"
                )

            child_run_id = str(uuid4())
            delegation_id = str(uuid4())
            now = self._utc_now()
            session.add(
                AgentRun(
                    id=child_run_id,
                    session_id=parent.session_id,
                    agent_id=target.id,
                    parent_run_id=parent.id,
                    depth=child_depth,
                    provider_id=target.provider_id,
                    model_id=target.model_id,
                    model_name=model_name,
                    status="queued",
                    output_text="",
                    cancel_requested=False,
                )
            )
            session.add(
                Delegation(
                    id=delegation_id,
                    parent_run_id=parent.id,
                    root_run_id=root_run_id,
                    child_run_id=child_run_id,
                    team_id=team.team_id,
                    source_agent_id=parent.agent_id,
                    target_agent_id=target.id,
                    task=arguments.task,
                    status="running",
                    result_text="",
                    depth=child_depth,
                    started_at=now,
                )
            )
            await self._add_event(
                session,
                parent.id,
                "delegation.started",
                {
                    "delegation_id": delegation_id,
                    "parent_run_id": parent.id,
                    "child_run_id": child_run_id,
                    "team_id": team.team_id,
                    "target_agent_id": target.id,
                    "target_agent_name": target.name,
                    "task": arguments.task[: self.settings.tool_event_preview_chars],
                    "depth": child_depth,
                },
            )
            await session.commit()

        await self._execute(child_run_id, propagate_cancel=True)

        async with self.session_factory() as session:
            delegation = await session.get(Delegation, delegation_id)
            child = await session.get(AgentRun, child_run_id)
            if delegation is None or child is None:
                return ToolExecutionResult(
                    status="failed",
                    arguments=argument_data,
                    payload={"ok": False, "error": "Delegation audit disappeared"},
                    error_message="Delegation audit disappeared",
                )
            now = self._utc_now()
            delegation.status = child.status
            delegation.result_text = child.output_text
            delegation.error_message = child.error_message
            delegation.finished_at = now
            delegation.duration_ms = max(
                0,
                round((now - (delegation.started_at or now)).total_seconds() * 1000),
            )
            completed = child.status == "completed"
            event_type = "delegation.completed" if completed else "delegation.failed"
            target_name = await session.scalar(
                select(Agent.name).where(Agent.id == delegation.target_agent_id)
            )
            await self._add_event(
                session,
                run_id,
                event_type,
                {
                    "delegation_id": delegation.id,
                    "child_run_id": child.id,
                    "target_agent_id": delegation.target_agent_id,
                    "target_agent_name": target_name or delegation.target_agent_id,
                    "status": child.status,
                    "duration_ms": delegation.duration_ms,
                    **(
                        {"message": child.error_message or "Delegated Run failed"}
                        if not completed
                        else {}
                    ),
                },
            )
            await session.commit()
            if completed:
                bounded_result = child.output_text[
                    : self.settings.tool_result_max_chars
                ]
                return ToolExecutionResult(
                    status="completed",
                    arguments=argument_data,
                    payload={
                        "ok": True,
                        "delegation_id": delegation.id,
                        "target_agent_id": delegation.target_agent_id,
                        "result": bounded_result,
                        "truncated": len(child.output_text) > len(bounded_result),
                    },
                )
            message = child.error_message or f"Delegated Run became {child.status}"
            return ToolExecutionResult(
                status="failed",
                arguments=argument_data,
                payload={
                    "ok": False,
                    "delegation_id": delegation.id,
                    "status": child.status,
                    "error": message,
                },
                error_message=message,
            )

    async def _delegation_teams(
        self,
        session: AsyncSession,
        agent: Agent,
    ) -> tuple[DelegationTeam, ...]:
        if not agent.is_coordinator:
            return ()
        teams = (
            await session.scalars(
                select(Team)
                .where(
                    Team.coordinator_agent_id == agent.id,
                    Team.status == "active",
                )
                .order_by(Team.created_at, Team.name)
            )
        ).all()
        capabilities: list[DelegationTeam] = []
        for team in teams:
            members = (
                await session.scalars(
                    select(Agent)
                    .join(TeamMember, TeamMember.agent_id == Agent.id)
                    .where(
                        TeamMember.team_id == team.id,
                        TeamMember.role == "member",
                        Agent.status == "active",
                    )
                    .order_by(TeamMember.created_at)
                )
            ).all()
            if members:
                capabilities.append(
                    DelegationTeam(
                        team_id=team.id,
                        name=team.name,
                        members=tuple(
                            DelegationMember(
                                agent_id=member.id,
                                name=member.name,
                                description=member.description,
                            )
                            for member in members
                        ),
                    )
                )
        return tuple(capabilities)

    async def _run_ancestry(
        self,
        session: AsyncSession,
        run: AgentRun,
    ) -> tuple[str, set[str]]:
        current = run
        agent_ids = {current.agent_id}
        while current.parent_run_id is not None:
            parent = await session.get(AgentRun, current.parent_run_id)
            if parent is None:
                break
            current = parent
            agent_ids.add(current.agent_id)
        return current.id, agent_ids

    async def _assert_run_active(self, run_id: str) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if (
                run is None
                or run.status in TERMINAL_RUN_STATUSES
                or run.cancel_requested
                or run.status == "cancelling"
            ):
                raise RunCancelledError(run_id)

    @staticmethod
    def _delegation_rejected(
        arguments: dict[str, object], message: str
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            status="rejected",
            arguments=arguments,
            payload={"ok": False, "status": "rejected", "error": message},
            error_message=message,
        )

    @staticmethod
    def _assistant_tool_calls(
        run_id: str,
        pending_calls: dict[int, PendingToolCall],
    ) -> list[dict[str, object]]:
        calls: list[dict[str, object]] = []
        for pending in sorted(pending_calls.values(), key=lambda item: item.index):
            provider_call_id = pending.call_id or f"call_{run_id}_{pending.index}"
            calls.append(
                {
                    "id": provider_call_id,
                    "type": "function",
                    "function": {
                        "name": pending.name,
                        "arguments": pending.arguments or "{}",
                    },
                }
            )
        return calls

    def _event_preview(self, payload: dict[str, object]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        return serialized[: self.settings.tool_event_preview_chars]

    def _arguments_for_audit(self, raw_arguments: str) -> dict[str, object]:
        try:
            decoded = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return {str(key): value for key, value in decoded.items()}
        return {"_raw": raw_arguments[: self.settings.tool_event_preview_chars]}

    async def _append_delta(self, run_id: str, content: str) -> None:
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                raise RunCancelledError(run_id)
            if run.cancel_requested or run.status == "cancelling":
                raise RunCancelledError(run_id)
            run.output_text += content
            await self._add_event(
                session,
                run.id,
                "run.delta",
                {"run_id": run.id, "content": content},
            )
            await session.commit()

    async def _finish_completed(self, run_id: str) -> None:
        await self._finish_terminal(run_id, status="completed", error_message=None)

    async def _finish_cancelled(self, run_id: str) -> None:
        await self._finish_terminal(run_id, status="cancelled", error_message=None)

    async def _finish_failed(self, run_id: str, message: str) -> None:
        await self._finish_terminal(run_id, status="failed", error_message=message)

    async def _finish_terminal(
        self,
        run_id: str,
        *,
        status: str,
        error_message: str | None,
    ) -> None:
        outbound_message_id: str | None = None
        async with self.session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                return
            now = self._utc_now()
            run.status = status
            run.cancel_requested = status == "cancelled"
            run.error_message = error_message
            run.finished_at = now
            run.duration_ms = self._duration_ms(run, now)

            if run.parent_run_id is not None:
                delegation = await session.scalar(
                    select(Delegation).where(Delegation.child_run_id == run.id)
                )
                if delegation is not None:
                    delegation.status = status
                    delegation.result_text = run.output_text
                    delegation.error_message = error_message
                    delegation.finished_at = now
                    delegation.duration_ms = self._duration_ms(run, now)

            unfinished_tool_calls = (
                await session.scalars(
                    select(ToolCall).where(
                        ToolCall.run_id == run.id,
                        ToolCall.status.in_(("requested", "running")),
                    )
                )
            ).all()
            for tool_call in unfinished_tool_calls:
                tool_call.status = "failed"
                tool_call.error_message = (
                    f"Run became {status} before Tool execution finished"
                )
                tool_call.finished_at = now
                tool_call.duration_ms = (
                    max(
                        0,
                        round((now - tool_call.started_at).total_seconds() * 1000),
                    )
                    if tool_call.started_at is not None
                    else 0
                )
                await self._add_event(
                    session,
                    run.id,
                    "tool.failed",
                    {
                        "run_id": run.id,
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_call.tool_name,
                        "status": "failed",
                        "duration_ms": tool_call.duration_ms,
                        "message": tool_call.error_message,
                    },
                )

            if run.output_text and run.parent_run_id is None:
                assistant_exists = await session.scalar(
                    select(Message.id)
                    .where(Message.run_id == run.id, Message.role == "assistant")
                    .limit(1)
                )
                if assistant_exists is None:
                    next_sequence = (
                        await session.scalar(
                            select(func.coalesce(func.max(Message.sequence), 0)).where(
                                Message.session_id == run.session_id
                            )
                        )
                    ) + 1
                    session.add(
                        Message(
                            id=str(uuid4()),
                            session_id=run.session_id,
                            run_id=run.id,
                            role="assistant",
                            content=run.output_text,
                            status="final" if status == "completed" else "partial",
                            sequence=next_sequence,
                        )
                    )
            if run.parent_run_id is None:
                external = await session.scalar(
                    select(ExternalConversation).where(
                        ExternalConversation.chat_session_id == run.session_id
                    )
                )
                if external is not None:
                    inbound = await session.scalar(
                        select(ChannelMessage).where(
                            ChannelMessage.run_id == run.id,
                            ChannelMessage.direction == "inbound",
                        )
                    )
                    if inbound is not None:
                        inbound.status = status
                        inbound.error_message = error_message
                    reply = self._channel_reply(run.output_text, status, error_message)
                    outbound_message_id = str(uuid4())
                    session.add(
                        ChannelMessage(
                            id=outbound_message_id,
                            channel_id=external.channel_id,
                            external_conversation_id=(
                                external.external_conversation_id
                            ),
                            external_user_id=external.external_user_id,
                            external_message_id=f"run:{run.id}",
                            direction="outbound",
                            content=reply,
                            status="pending",
                            chat_session_id=run.session_id,
                            run_id=run.id,
                            attempts=0,
                        )
                    )
            chat = await session.get(ChatSession, run.session_id)
            if chat is not None:
                chat.updated_at = now

            event_type = f"run.{status}"
            data: dict[str, object] = {
                "run_id": run.id,
                "status": status,
                "duration_ms": run.duration_ms or 0,
            }
            if error_message is not None:
                data["message"] = error_message
            if run.output_text and status != "completed":
                data["partial"] = True
            await self._add_event(session, run.id, event_type, data)
            await session.commit()
        if outbound_message_id is not None and self.channel_dispatcher is not None:
            self.channel_dispatcher.dispatch(outbound_message_id)

    @staticmethod
    def _channel_reply(output_text: str, status: str, error_message: str | None) -> str:
        if output_text:
            return output_text
        if status == "cancelled":
            return "本次任务已取消。"
        if error_message:
            return "任务执行失败，请稍后重试或联系管理员查看运行日志。"
        return "任务未能生成回复，请稍后重试。"

    @staticmethod
    async def _add_event(
        session: AsyncSession,
        run_id: str,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        sequence = (
            await session.scalar(
                select(func.coalesce(func.max(RunEvent.sequence), 0)).where(
                    RunEvent.run_id == run_id
                )
            )
        ) + 1
        session.add(
            RunEvent(
                id=str(uuid4()),
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                data_json=data,
            )
        )

    @staticmethod
    def _duration_ms(run: AgentRun, now: datetime) -> int:
        started_at = run.started_at or run.created_at
        return max(0, round((now - started_at).total_seconds() * 1000))

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
