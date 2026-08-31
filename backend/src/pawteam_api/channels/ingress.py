"""Normalize external messages into durable chats and Agent Runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.models import (
    Agent,
    AgentRun,
    Channel,
    ChannelMessage,
    ChatSession,
    ExternalConversation,
    Message,
    ProviderModel,
)
from pawteam_api.runtime.service import ACTIVE_RUN_STATUSES


class ChannelIngressError(ValueError):
    pass


@dataclass(frozen=True)
class IngressResult:
    duplicate: bool
    channel_message_id: str
    chat_session_id: str
    run_id: str | None
    outbound_message_id: str | None = None


class ChannelIngressService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def receive_text(
        self,
        *,
        channel: Channel,
        external_conversation_id: str,
        external_user_id: str,
        external_message_id: str,
        content: str,
    ) -> IngressResult:
        duplicate = await self.session.scalar(
            select(ChannelMessage).where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.direction == "inbound",
                ChannelMessage.external_message_id == external_message_id,
            )
        )
        if duplicate is not None:
            return IngressResult(
                duplicate=True,
                channel_message_id=duplicate.id,
                chat_session_id=duplicate.chat_session_id,
                run_id=duplicate.run_id,
                outbound_message_id=None,
            )

        row = (
            await self.session.execute(
                select(Agent, ProviderModel.model_name)
                .join(ProviderModel, ProviderModel.id == Agent.model_id)
                .where(Agent.id == channel.agent_id)
            )
        ).one_or_none()
        if row is None:
            raise ChannelIngressError("Channel Agent or model does not exist")
        agent, model_name = row
        if agent.status != "active":
            raise ChannelIngressError("Channel Agent is disabled")

        mapping = await self.session.scalar(
            select(ExternalConversation).where(
                ExternalConversation.channel_id == channel.id,
                ExternalConversation.external_conversation_id
                == external_conversation_id,
            )
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        if mapping is None:
            chat = ChatSession(
                id=str(uuid4()),
                agent_id=agent.id,
                title=self._title(content),
                channel="wecom",
                status="active",
                updated_at=now,
            )
            mapping = ExternalConversation(
                id=str(uuid4()),
                channel_id=channel.id,
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                chat_session_id=chat.id,
                updated_at=now,
            )
            self.session.add_all([chat, mapping])
        else:
            chat = await self.session.get(ChatSession, mapping.chat_session_id)
            if chat is None:
                raise ChannelIngressError("Mapped chat does not exist")
            mapping.external_user_id = external_user_id
            mapping.updated_at = now

        channel_message = ChannelMessage(
            id=str(uuid4()),
            channel_id=channel.id,
            external_conversation_id=external_conversation_id,
            external_user_id=external_user_id,
            external_message_id=external_message_id,
            direction="inbound",
            content=content,
            status="received",
            chat_session_id=chat.id,
            run_id=None,
            attempts=0,
        )

        active_run = await self.session.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.session_id == chat.id,
                AgentRun.parent_run_id.is_(None),
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        run: AgentRun | None = None
        busy_reply: ChannelMessage | None = None
        if active_run is None:
            next_sequence = (
                await self.session.scalar(
                    select(func.coalesce(func.max(Message.sequence), 0)).where(
                        Message.session_id == chat.id
                    )
                )
            ) + 1
            run = AgentRun(
                id=str(uuid4()),
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
            user_message = Message(
                id=str(uuid4()),
                session_id=chat.id,
                run_id=run.id,
                role="user",
                content=content,
                status="final",
                sequence=next_sequence,
            )
            channel_message.run_id = run.id
            channel_message.status = "processing"
            self.session.add_all([run, user_message])
        else:
            channel_message.status = "rejected_busy"
            channel_message.error_message = (
                "This conversation already has an active Run"
            )
            busy_reply = ChannelMessage(
                id=str(uuid4()),
                channel_id=channel.id,
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_message_id=f"busy:{external_message_id}",
                direction="outbound",
                content="上一条消息仍在处理中，请稍后重新发送本条消息。",
                status="pending",
                chat_session_id=chat.id,
                run_id=None,
                attempts=0,
            )
            self.session.add(busy_reply)

        chat.updated_at = now
        self.session.add(channel_message)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            duplicate = await self.session.scalar(
                select(ChannelMessage).where(
                    ChannelMessage.channel_id == channel.id,
                    ChannelMessage.direction == "inbound",
                    ChannelMessage.external_message_id == external_message_id,
                )
            )
            if duplicate is None:
                raise ChannelIngressError("Unable to persist inbound message") from exc
            return IngressResult(
                duplicate=True,
                channel_message_id=duplicate.id,
                chat_session_id=duplicate.chat_session_id,
                run_id=duplicate.run_id,
                outbound_message_id=None,
            )
        return IngressResult(
            duplicate=False,
            channel_message_id=channel_message.id,
            chat_session_id=chat.id,
            run_id=run.id if run is not None else None,
            outbound_message_id=busy_reply.id if busy_reply is not None else None,
        )

    @staticmethod
    def _title(content: str) -> str:
        compact = " ".join(content.split())
        return compact if len(compact) <= 30 else f"{compact[:30]}…"
