"""CRUD for durable chat sessions and commands that create or cancel Runs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.chat_schemas import (
    ChatCreate,
    ChatDetailResponse,
    ChatSessionResponse,
    MessageResponse,
    RunCreate,
    RunResponse,
)
from pawteam_api.models import (
    Agent,
    AgentRun,
    ChatSession,
    Delegation,
    Message,
    ProviderModel,
    Team,
    ToolCall,
)
from pawteam_api.team_schemas import DelegationResponse
from pawteam_api.tool_schemas import ToolCallResponse

ACTIVE_RUN_STATUSES = ("queued", "running", "cancelling")
TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")


class ChatNotFoundError(LookupError):
    pass


class ChatConflictError(ValueError):
    pass


class ChatConfigurationError(ValueError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunConflictError(ValueError):
    pass


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: ChatCreate) -> ChatSessionResponse:
        agent = await self.session.get(Agent, payload.agent_id)
        if agent is None:
            raise ChatConfigurationError("Selected Agent does not exist")
        if agent.status != "active":
            raise ChatConfigurationError("Selected Agent is disabled")
        chat = ChatSession(
            id=str(uuid4()),
            agent_id=agent.id,
            title=payload.title or "新会话",
            channel="console",
            status="active",
        )
        self.session.add(chat)
        await self.session.commit()
        await self.session.refresh(chat)
        return self._session_response(chat, agent.name)

    async def list(self, agent_id: str | None) -> list[ChatSessionResponse]:
        query = (
            select(ChatSession, Agent.name)
            .join(Agent, Agent.id == ChatSession.agent_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        )
        if agent_id is not None:
            query = query.where(ChatSession.agent_id == agent_id)
        rows = (await self.session.execute(query)).all()
        return [self._session_response(chat, agent_name) for chat, agent_name in rows]

    async def get(self, chat_id: str) -> ChatDetailResponse:
        row = (
            await self.session.execute(
                select(ChatSession, Agent.name)
                .join(Agent, Agent.id == ChatSession.agent_id)
                .where(ChatSession.id == chat_id)
            )
        ).one_or_none()
        if row is None:
            raise ChatNotFoundError(chat_id)
        chat, agent_name = row
        messages = (
            await self.session.scalars(
                select(Message)
                .where(Message.session_id == chat_id)
                .order_by(Message.sequence)
            )
        ).all()
        runs = (
            await self.session.scalars(
                select(AgentRun)
                .where(AgentRun.session_id == chat_id)
                .order_by(AgentRun.created_at)
            )
        ).all()
        run_ids = [run.id for run in runs]
        tool_calls = (
            (
                await self.session.scalars(
                    select(ToolCall)
                    .where(ToolCall.run_id.in_(run_ids))
                    .order_by(ToolCall.created_at)
                )
            ).all()
            if run_ids
            else []
        )
        delegations = (
            (
                await self.session.scalars(
                    select(Delegation)
                    .where(Delegation.root_run_id.in_(run_ids))
                    .order_by(Delegation.created_at)
                )
            ).all()
            if run_ids
            else []
        )
        return ChatDetailResponse(
            session=self._session_response(chat, agent_name),
            messages=[self._message_response(message) for message in messages],
            runs=[run_response(run) for run in runs],
            tool_calls=[tool_call_response(tool_call) for tool_call in tool_calls],
            delegations=[
                await self._delegation_response(delegation)
                for delegation in delegations
            ],
        )

    async def _delegation_response(self, delegation: Delegation) -> DelegationResponse:
        team = await self.session.get(Team, delegation.team_id)
        source = await self.session.get(Agent, delegation.source_agent_id)
        target = await self.session.get(Agent, delegation.target_agent_id)
        return DelegationResponse(
            id=delegation.id,
            parent_run_id=delegation.parent_run_id,
            child_run_id=delegation.child_run_id,
            team_id=delegation.team_id,
            team_name=team.name if team is not None else "Deleted Team",
            source_agent_id=delegation.source_agent_id,
            source_agent_name=source.name if source is not None else "Deleted Agent",
            target_agent_id=delegation.target_agent_id,
            target_agent_name=target.name if target is not None else "Deleted Agent",
            task=delegation.task,
            status=delegation.status,
            result_text=delegation.result_text,
            error_message=delegation.error_message,
            depth=delegation.depth,
            duration_ms=delegation.duration_ms,
            created_at=delegation.created_at,
            started_at=delegation.started_at,
            finished_at=delegation.finished_at,
        )

    @staticmethod
    def _session_response(chat: ChatSession, agent_name: str) -> ChatSessionResponse:
        return ChatSessionResponse(
            id=chat.id,
            agent_id=chat.agent_id,
            agent_name=agent_name,
            title=chat.title,
            channel=chat.channel,
            status=chat.status,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
        )

    @staticmethod
    def _message_response(message: Message) -> MessageResponse:
        return MessageResponse(
            id=message.id,
            session_id=message.session_id,
            run_id=message.run_id,
            role=message.role,
            content=message.content,
            status=message.status,
            sequence=message.sequence,
            created_at=message.created_at,
        )


class RunCommandService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, chat_id: str, payload: RunCreate) -> RunResponse:
        row = (
            await self.session.execute(
                select(ChatSession, Agent, ProviderModel.model_name)
                .join(Agent, Agent.id == ChatSession.agent_id)
                .join(ProviderModel, ProviderModel.id == Agent.model_id)
                .where(ChatSession.id == chat_id)
            )
        ).one_or_none()
        if row is None:
            raise ChatNotFoundError(chat_id)
        chat, agent, model_name = row
        if chat.status != "active":
            raise ChatConflictError("Chat is archived")
        if agent.status != "active":
            raise ChatConfigurationError("Agent is disabled")
        active_run_id = await self.session.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.session_id == chat_id,
                AgentRun.parent_run_id.is_(None),
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        if active_run_id is not None:
            raise RunConflictError("This chat already has an active Run")

        next_sequence = (
            await self.session.scalar(
                select(func.coalesce(func.max(Message.sequence), 0)).where(
                    Message.session_id == chat_id
                )
            )
        ) + 1
        run_id = str(uuid4())
        run = AgentRun(
            id=run_id,
            session_id=chat.id,
            agent_id=agent.id,
            parent_run_id=None,
            depth=0,
            provider_id=agent.provider_id,
            model_id=agent.model_id,
            model_name=model_name,
            status="queued",
            output_text="",
            cancel_requested=False,
        )
        message = Message(
            id=str(uuid4()),
            session_id=chat.id,
            run_id=run_id,
            role="user",
            content=payload.content,
            status="final",
            sequence=next_sequence,
        )
        if chat.title == "新会话":
            chat.title = self._title(payload.content)
        chat.updated_at = self._utc_now()
        self.session.add_all([run, message])
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise RunConflictError("This chat already has an active Run") from exc
        await self.session.refresh(run)
        return run_response(run)

    async def get(self, run_id: str) -> RunResponse:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        return run_response(run)

    async def request_cancel(self, run_id: str) -> RunResponse:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return run_response(run)
        run.cancel_requested = True
        run.status = "cancelling"
        await self.session.commit()
        return run_response(run)

    @staticmethod
    def _title(content: str) -> str:
        compact = " ".join(content.split())
        return compact if len(compact) <= 30 else f"{compact[:30]}…"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)


def run_response(run: AgentRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        session_id=run.session_id,
        agent_id=run.agent_id,
        parent_run_id=run.parent_run_id,
        depth=run.depth,
        provider_id=run.provider_id,
        model_id=run.model_id,
        model_name=run.model_name,
        status=run.status,
        output_text=run.output_text,
        error_message=run.error_message,
        cancel_requested=run.cancel_requested,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def tool_call_response(tool_call: ToolCall) -> ToolCallResponse:
    return ToolCallResponse(
        id=tool_call.id,
        run_id=tool_call.run_id,
        provider_call_id=tool_call.provider_call_id,
        tool_name=tool_call.tool_name,
        arguments=dict(tool_call.arguments_json),
        status=tool_call.status,
        result=(
            dict(tool_call.result_json) if tool_call.result_json is not None else None
        ),
        error_message=tool_call.error_message,
        started_at=tool_call.started_at,
        finished_at=tool_call.finished_at,
        duration_ms=tool_call.duration_ms,
        created_at=tool_call.created_at,
    )
