"""Merge the server Tool registry with explicit per-Agent enablement."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.models import Agent, AgentTool
from pawteam_api.tool_schemas import ToolAssignmentResponse
from pawteam_api.tools.registry import ToolRegistry


class ToolConfigurationError(ValueError):
    pass


class ToolNotFoundError(LookupError):
    pass


class ToolAssignmentService:
    def __init__(self, session: AsyncSession, registry: ToolRegistry) -> None:
        self.session = session
        self.registry = registry

    async def list(self, agent_id: str) -> list[ToolAssignmentResponse]:
        await self._agent(agent_id)
        assignments = {
            assignment.tool_name: assignment
            for assignment in (
                await self.session.scalars(
                    select(AgentTool).where(AgentTool.agent_id == agent_id)
                )
            ).all()
        }
        return [
            ToolAssignmentResponse(
                name=definition.name,
                description=definition.description,
                enabled=(
                    assignments.get(definition.name).enabled
                    if definition.name in assignments
                    else False
                ),
                input_schema=definition.arguments_model.model_json_schema(),
            )
            for definition in self.registry.definitions()
        ]

    async def toggle(
        self,
        agent_id: str,
        tool_name: str,
    ) -> ToolAssignmentResponse:
        await self._agent(agent_id)
        if not self.registry.contains(tool_name):
            raise ToolNotFoundError(tool_name)
        assignment = await self.session.scalar(
            select(AgentTool).where(
                AgentTool.agent_id == agent_id,
                AgentTool.tool_name == tool_name,
            )
        )
        if assignment is None:
            assignment = AgentTool(
                id=str(uuid4()),
                agent_id=agent_id,
                tool_name=tool_name,
                enabled=True,
                config_json={},
            )
            self.session.add(assignment)
        else:
            assignment.enabled = not assignment.enabled
        await self.session.commit()
        return next(
            item for item in await self.list(agent_id) if item.name == tool_name
        )

    async def _agent(self, agent_id: str) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise ToolConfigurationError("Agent does not exist")
        return agent
