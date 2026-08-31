"""CRUD for coordinator-owned Team membership allowlists."""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.models import Agent, Delegation, Team, TeamMember
from pawteam_api.team_schemas import (
    TeamCreate,
    TeamMemberResponse,
    TeamResponse,
    TeamUpdate,
)


class TeamNotFoundError(LookupError):
    pass


class TeamConflictError(ValueError):
    pass


class TeamConfigurationError(ValueError):
    pass


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[TeamResponse]:
        teams = (
            await self.session.scalars(
                select(Team).order_by(Team.created_at, Team.name)
            )
        ).all()
        return [await self._response(team) for team in teams]

    async def get(self, team_id: str) -> TeamResponse:
        return await self._response(await self._team(team_id))

    async def create(self, payload: TeamCreate) -> TeamResponse:
        await self._validate_agents(
            payload.coordinator_agent_id, payload.member_agent_ids
        )
        team = Team(
            id=str(uuid4()),
            name=payload.name,
            description=payload.description,
            coordinator_agent_id=payload.coordinator_agent_id,
            status="active",
            version=1,
        )
        self.session.add(team)
        self._add_members(
            team.id, payload.coordinator_agent_id, payload.member_agent_ids
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise TeamConflictError("Team name already exists") from exc
        await self.session.refresh(team)
        return await self._response(team)

    async def update(self, team_id: str, payload: TeamUpdate) -> TeamResponse:
        team = await self._team(team_id)
        if team.version != payload.expected_version:
            raise TeamConflictError(
                "Team was changed by another request; "
                f"current version is {team.version}"
            )
        await self._validate_agents(
            payload.coordinator_agent_id, payload.member_agent_ids
        )
        team.name = payload.name
        team.description = payload.description
        team.coordinator_agent_id = payload.coordinator_agent_id
        team.version += 1
        await self.session.execute(
            delete(TeamMember).where(TeamMember.team_id == team.id)
        )
        self._add_members(
            team.id, payload.coordinator_agent_id, payload.member_agent_ids
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise TeamConflictError("Team name already exists") from exc
        await self.session.refresh(team)
        return await self._response(team)

    async def toggle(self, team_id: str) -> TeamResponse:
        team = await self._team(team_id)
        team.status = "disabled" if team.status == "active" else "active"
        team.version += 1
        await self.session.commit()
        await self.session.refresh(team)
        return await self._response(team)

    async def delete(self, team_id: str) -> None:
        team = await self._team(team_id)
        has_history = await self.session.scalar(
            select(Delegation.id).where(Delegation.team_id == team.id).limit(1)
        )
        if has_history is not None:
            raise TeamConflictError(
                "Team has delegation history; disable it instead of deleting it"
            )
        await self.session.delete(team)
        await self.session.commit()

    async def _validate_agents(
        self,
        coordinator_agent_id: str,
        member_agent_ids: list[str],
    ) -> None:
        requested_ids = {coordinator_agent_id, *member_agent_ids}
        agents = {
            agent.id: agent
            for agent in (
                await self.session.scalars(
                    select(Agent).where(Agent.id.in_(requested_ids))
                )
            ).all()
        }
        missing = requested_ids - agents.keys()
        if missing:
            raise TeamConfigurationError("One or more selected Agents do not exist")
        coordinator = agents[coordinator_agent_id]
        if not coordinator.is_coordinator:
            raise TeamConfigurationError(
                "Selected coordinator Agent is not marked as a coordinator"
            )
        if coordinator.status != "active":
            raise TeamConfigurationError("Coordinator Agent is disabled")
        if any(agents[agent_id].status != "active" for agent_id in member_agent_ids):
            raise TeamConfigurationError("All Team members must be active Agents")

    def _add_members(
        self,
        team_id: str,
        coordinator_agent_id: str,
        member_agent_ids: list[str],
    ) -> None:
        self.session.add(
            TeamMember(
                id=str(uuid4()),
                team_id=team_id,
                agent_id=coordinator_agent_id,
                role="coordinator",
            )
        )
        for agent_id in member_agent_ids:
            self.session.add(
                TeamMember(
                    id=str(uuid4()),
                    team_id=team_id,
                    agent_id=agent_id,
                    role="member",
                )
            )

    async def _team(self, team_id: str) -> Team:
        team = await self.session.get(Team, team_id)
        if team is None:
            raise TeamNotFoundError(team_id)
        return team

    async def _response(self, team: Team) -> TeamResponse:
        rows = (
            await self.session.execute(
                select(TeamMember, Agent)
                .join(Agent, Agent.id == TeamMember.agent_id)
                .where(TeamMember.team_id == team.id)
                .order_by(TeamMember.role, TeamMember.created_at)
            )
        ).all()
        members = [
            TeamMemberResponse(
                agent_id=agent.id,
                agent_name=agent.name,
                role=membership.role,
                agent_status=agent.status,
            )
            for membership, agent in rows
        ]
        coordinator_name = next(
            member.agent_name for member in members if member.role == "coordinator"
        )
        return TeamResponse(
            id=team.id,
            name=team.name,
            description=team.description,
            coordinator_agent_id=team.coordinator_agent_id,
            coordinator_agent_name=coordinator_name,
            status=team.status,
            members=members,
            version=team.version,
            created_at=team.created_at,
            updated_at=team.updated_at,
        )
