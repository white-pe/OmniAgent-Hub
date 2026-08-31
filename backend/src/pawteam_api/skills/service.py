"""Coordinate Skill metadata with per-Agent Workspace SKILL.md files."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.models import Agent, Skill
from pawteam_api.skill_schemas import SkillCreate, SkillResponse, SkillUpdate
from pawteam_api.workspaces.store import WorkspaceStore


class SkillNotFoundError(LookupError):
    pass


class SkillConflictError(ValueError):
    pass


class SkillConfigurationError(ValueError):
    pass


class SkillService:
    def __init__(self, session: AsyncSession, workspace_store: WorkspaceStore) -> None:
        self.session = session
        self.workspace_store = workspace_store

    async def list(self, agent_id: str) -> list[SkillResponse]:
        agent = await self._agent(agent_id)
        skills = (
            await self.session.scalars(
                select(Skill)
                .where(Skill.agent_id == agent_id)
                .order_by(Skill.created_at, Skill.name)
            )
        ).all()
        return [self._response(agent, skill) for skill in skills]

    async def create(self, agent_id: str, payload: SkillCreate) -> SkillResponse:
        agent = await self._agent(agent_id)
        staging: Path | None = None
        final_directory: Path | None = None
        skill_id = str(uuid4())
        try:
            staging = self.workspace_store.prepare_skill(
                agent.workspace_path, payload.name, payload.content
            )
            relative_path = self.workspace_store.finalize_skill(
                staging, agent.workspace_path, payload.name
            )
            staging = None
            final_directory = (
                self.workspace_store.root / agent.workspace_path / relative_path
            )
            skill = Skill(
                id=skill_id,
                agent_id=agent.id,
                name=payload.name,
                description=payload.description,
                path=relative_path,
                enabled=payload.enabled,
                channel_scope_json=payload.channel_scope,
                config_json=payload.config,
                version=1,
            )
            self.session.add(skill)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self._cleanup(staging, final_directory)
            raise SkillConflictError(
                "Skill name already exists for this Agent"
            ) from exc
        except Exception:
            await self.session.rollback()
            self._cleanup(staging, final_directory)
            raise
        return await self.get(agent_id, payload.name)

    async def get(self, agent_id: str, skill_name: str) -> SkillResponse:
        agent = await self._agent(agent_id)
        skill = await self._skill(agent_id, skill_name)
        return self._response(agent, skill)

    async def update(
        self,
        agent_id: str,
        skill_name: str,
        payload: SkillUpdate,
    ) -> SkillResponse:
        agent = await self._agent(agent_id)
        skill = await self._skill(agent_id, skill_name)
        self._check_version(skill, payload.expected_version)
        previous_content: str | None = None
        changes = payload.model_fields_set
        if "content" in changes and payload.content is not None:
            previous_content = self.workspace_store.write_skill(
                agent.workspace_path, skill.path, payload.content
            )
        if "description" in changes and payload.description is not None:
            skill.description = payload.description
        if "enabled" in changes and payload.enabled is not None:
            skill.enabled = payload.enabled
        if "channel_scope" in changes and payload.channel_scope is not None:
            skill.channel_scope_json = payload.channel_scope
        if "config" in changes and payload.config is not None:
            skill.config_json = payload.config
        skill.version += 1
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            if previous_content is not None:
                self.workspace_store.write_skill(
                    agent.workspace_path, skill.path, previous_content
                )
            raise
        return await self.get(agent_id, skill_name)

    async def toggle(self, agent_id: str, skill_name: str) -> SkillResponse:
        skill = await self._skill(agent_id, skill_name)
        skill.enabled = not skill.enabled
        skill.version += 1
        await self.session.commit()
        return await self.get(agent_id, skill_name)

    async def delete(self, agent_id: str, skill_name: str) -> None:
        agent = await self._agent(agent_id)
        skill = await self._skill(agent_id, skill_name)
        original, trashed = self.workspace_store.stage_delete_skill(
            agent.workspace_path, skill.path
        )
        try:
            await self.session.delete(skill)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self.workspace_store.restore_delete(original, trashed)
            raise
        try:
            self.workspace_store.purge(trashed)
        except OSError:
            pass

    async def _agent(self, agent_id: str) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise SkillConfigurationError("Agent does not exist")
        return agent

    async def _skill(self, agent_id: str, skill_name: str) -> Skill:
        skill = await self.session.scalar(
            select(Skill).where(
                Skill.agent_id == agent_id,
                Skill.name == skill_name,
            )
        )
        if skill is None:
            raise SkillNotFoundError(skill_name)
        return skill

    def _response(self, agent: Agent, skill: Skill) -> SkillResponse:
        return SkillResponse(
            id=skill.id,
            agent_id=skill.agent_id,
            name=skill.name,
            description=skill.description,
            path=skill.path,
            content=self.workspace_store.read_skill(agent.workspace_path, skill.path),
            enabled=skill.enabled,
            channel_scope=list(skill.channel_scope_json),
            config=dict(skill.config_json),
            version=skill.version,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    @staticmethod
    def _check_version(skill: Skill, expected_version: int) -> None:
        if skill.version != expected_version:
            raise SkillConflictError(
                "Skill was changed by another request; "
                f"current version is {skill.version}"
            )

    def _cleanup(self, staging: Path | None, final_directory: Path | None) -> None:
        if staging is not None and staging.exists():
            self.workspace_store.purge(staging)
        if final_directory is not None and final_directory.exists():
            self.workspace_store.purge(final_directory)
