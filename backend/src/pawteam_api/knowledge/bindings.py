"""Business operations for Agent-to-knowledge-base access bindings."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.knowledge_schemas import (
    KnowledgeBaseBindingResponse,
    KnowledgeBaseBindingUpdate,
)
from pawteam_api.models import Agent, AgentKnowledgeBinding, KnowledgeBase


class BindingNotFoundError(LookupError):
    """Raised when the requested Agent binding does not exist."""


class BindingConflictError(ValueError):
    """Raised for duplicate bindings or invalid binding operations."""


class BindingConfigurationError(ValueError):
    """Raised when an Agent or knowledge base does not exist."""


class KnowledgeBaseBindingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_agent(
        self,
        agent_id: str,
    ) -> list[KnowledgeBaseBindingResponse]:
        await self._require_agent(agent_id)

        rows = (
            await self.session.execute(
                select(AgentKnowledgeBinding, KnowledgeBase.name)
                .join(
                    KnowledgeBase,
                    KnowledgeBase.id
                    == AgentKnowledgeBinding.knowledge_base_id,
                )
                .where(AgentKnowledgeBinding.agent_id == agent_id)
                .order_by(KnowledgeBase.name)
            )
        ).all()

        return [
            self._response(binding, knowledge_base_name)
            for binding, knowledge_base_name in rows
        ]

    async def create(
        self,
        agent_id: str,
        knowledge_base_id: str,
    ) -> KnowledgeBaseBindingResponse:
        await self._require_agent(agent_id)
        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
        )
        if knowledge_base is None:
            raise BindingConfigurationError("Knowledge base does not exist")

        existing = await self.session.get(
            AgentKnowledgeBinding,
            (agent_id, knowledge_base_id),
        )
        if existing is not None:
            raise BindingConflictError("Knowledge base is already bound")

        binding = AgentKnowledgeBinding(
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            enabled=True,
        )
        self.session.add(binding)

        try:
            await self.session.commit()
            await self.session.refresh(binding)
        except IntegrityError as error:
            await self.session.rollback()
            raise BindingConflictError(
                "Knowledge base is already bound"
            ) from error

        return self._response(binding, knowledge_base.name)

    async def set_enabled(
        self,
        agent_id: str,
        knowledge_base_id: str,
        payload: KnowledgeBaseBindingUpdate,
    ) -> KnowledgeBaseBindingResponse:
        binding = await self._get_binding(agent_id, knowledge_base_id)
        binding.enabled = payload.enabled
        await self.session.commit()
        await self.session.refresh(binding)

        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
        )
        if knowledge_base is None:
            raise BindingConfigurationError("Knowledge base does not exist")

        return self._response(binding, knowledge_base.name)

    async def delete(self, agent_id: str, knowledge_base_id: str) -> None:
        binding = await self._get_binding(agent_id, knowledge_base_id)
        await self.session.delete(binding)
        await self.session.commit()

    async def _get_binding(
        self,
        agent_id: str,
        knowledge_base_id: str,
    ) -> AgentKnowledgeBinding:
        await self._require_agent(agent_id)
        binding = await self.session.get(
            AgentKnowledgeBinding,
            (agent_id, knowledge_base_id),
        )
        if binding is None:
            raise BindingNotFoundError("Knowledge base binding not found")
        return binding

    async def _require_agent(self, agent_id: str) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise BindingConfigurationError("Agent does not exist")
        return agent

    @staticmethod
    def _response(
        binding: AgentKnowledgeBinding,
        knowledge_base_name: str,
    ) -> KnowledgeBaseBindingResponse:
        return KnowledgeBaseBindingResponse(
            agent_id=binding.agent_id,
            knowledge_base_id=binding.knowledge_base_id,
            knowledge_base_name=knowledge_base_name,
            enabled=binding.enabled,
            created_at=binding.created_at,
        )