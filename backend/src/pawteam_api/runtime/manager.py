"""Background Agent execution with durable state and replayable events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.config import Settings
from pawteam_api.models import (
    Agent,
    AgentRun,
    ChatSession,
    Message,
    RunEvent,
)
from pawteam_api.providers.client import ProviderRequestError
from pawteam_api.providers.service import (
    ProviderConflictError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
    ProviderService,
)
from pawteam_api.runtime.prompt_builder import PromptBuilder
from pawteam_api.runtime.service import TERMINAL_RUN_STATUSES
from pawteam_api.security.secret_store import SecretNotFoundError, SecretStore
from pawteam_api.workspaces.store import WorkspaceError, WorkspaceStore

logger = logging.getLogger(__name__)


class RuntimeProviderClient(Protocol):
    def stream_messages(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncIterator[str]: ...


ProviderClientFactory = Callable[[str, str, float], RuntimeProviderClient]


class RunCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedRun:
    client: RuntimeProviderClient
    model_name: str
    messages: list[dict[str, str]]


class RunManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        secret_store: SecretStore,
        workspace_store: WorkspaceStore,
        provider_client_factory: ProviderClientFactory,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.secret_store = secret_store
        self.workspace_store = workspace_store
        self.provider_client_factory = provider_client_factory
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

    async def shutdown(self) -> None:
        running = [task for task in self.tasks.values() if not task.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    async def _execute(self, run_id: str) -> None:
        try:
            prepared = await self._prepare(run_id)
            if prepared is None:
                return
            received_content = False
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                async for content in prepared.client.stream_messages(
                    model=prepared.model_name,
                    messages=prepared.messages,
                    temperature=0.7,
                ):
                    if not content:
                        continue
                    received_content = True
                    await self._append_delta(run_id, content)
            if not received_content:
                raise ProviderRequestError("Provider returned no response content")
            await self._finish_completed(run_id)
        except asyncio.CancelledError:
            await self._finish_cancelled(run_id)
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
            history = (
                await session.scalars(
                    select(Message)
                    .where(Message.session_id == run.session_id)
                    .order_by(Message.sequence)
                )
            ).all()
            messages = self.prompt_builder.build(
                agent=agent,
                chat=chat,
                messages=list(history),
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
            return PreparedRun(
                client=client,
                model_name=runtime.model_name,
                messages=messages,
            )

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

            if run.output_text:
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
