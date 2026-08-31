"""Agent CRUD coordinated across SQLite and Workspace Markdown files."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.agent_schemas import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    WorkspaceFileResponse,
    WorkspaceFileUpdate,
)
from pawteam_api.models import Agent, Provider, ProviderModel
from pawteam_api.workspaces.store import WorkspaceStore


class AgentNotFoundError(LookupError):
    pass


class AgentConflictError(ValueError):
    pass


class AgentConfigurationError(ValueError):
    pass


class AgentService:
    def __init__(self, session: AsyncSession, workspace_store: WorkspaceStore) -> None:
        self.session = session
        self.workspace_store = workspace_store

    async def list(self) -> list[AgentResponse]:
        rows = (
            await self.session.execute(
                self._response_query().order_by(Agent.created_at, Agent.name)
            )
        ).all()
        return [self._response(*row) for row in rows]

    async def get(self, agent_id: str) -> AgentResponse:
        row = (await self.session.execute(self._response_query(agent_id))).one_or_none()
        if row is None:
            raise AgentNotFoundError(agent_id)
        return self._response(*row)

    async def create(
        self,
        payload: AgentCreate,
        *,
        workspace_files: Mapping[str, str] | None = None,
        before_commit: Callable[[str], None] | None = None,
    ) -> AgentResponse:
        agent_id = str(uuid4())
        staging: Path | None = None
        final_directory: Path | None = None
        try:
            await self._validate_model(payload.provider_id, payload.model_id)
            staging = self.workspace_store.prepare(
                agent_id,
                payload.name,
                payload.description,
                files=workspace_files,
            )
            workspace_path = self.workspace_store.finalize(staging, agent_id)
            staging = None
            final_directory = self.workspace_store.root / workspace_path
            agent = Agent(
                id=agent_id,
                name=payload.name,
                description=payload.description,
                status="active",
                workspace_path=workspace_path,
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                is_coordinator=payload.is_coordinator,
                version=1,
            )
            self.session.add(agent)
            if before_commit is not None:
                before_commit(agent_id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self._cleanup_create(staging, final_directory)
            raise AgentConflictError("Agent name already exists") from exc
        except Exception:
            await self.session.rollback()
            self._cleanup_create(staging, final_directory)
            raise
        return await self.get(agent_id)

    async def update(self, agent_id: str, payload: AgentUpdate) -> AgentResponse:
        agent = await self._entity(agent_id)
        self._check_version(agent, payload.expected_version)
        provider_id = payload.provider_id or agent.provider_id
        model_id = payload.model_id or agent.model_id
        await self._validate_model(provider_id, model_id)
        changes = payload.model_fields_set
        if "name" in changes and payload.name is not None:
            agent.name = payload.name
        if "description" in changes and payload.description is not None:
            agent.description = payload.description
        if "provider_id" in changes and payload.provider_id is not None:
            agent.provider_id = payload.provider_id
        if "model_id" in changes and payload.model_id is not None:
            agent.model_id = payload.model_id
        if "is_coordinator" in changes and payload.is_coordinator is not None:
            agent.is_coordinator = payload.is_coordinator
        agent.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AgentConflictError("Agent name already exists") from exc
        return await self.get(agent_id)

    async def toggle(self, agent_id: str) -> AgentResponse:
        agent = await self._entity(agent_id)
        agent.status = "disabled" if agent.status == "active" else "active"
        agent.version += 1
        await self.session.commit()
        return await self.get(agent_id)

    async def delete(self, agent_id: str) -> None:
        agent = await self._entity(agent_id)
        original, trashed = self.workspace_store.stage_delete(agent.workspace_path)
        try:
            await self.session.delete(agent)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self.workspace_store.restore_delete(original, trashed)
            raise AgentConflictError(
                "Agent has chat history and cannot be deleted"
            ) from exc
        except Exception:
            await self.session.rollback()
            self.workspace_store.restore_delete(original, trashed)
            raise
        try:
            self.workspace_store.purge(trashed)
        except OSError:
            pass

    async def get_file(self, agent_id: str, filename: str) -> WorkspaceFileResponse:
        agent = await self._entity(agent_id)
        return WorkspaceFileResponse(
            agent_id=agent.id,
            filename=filename,
            content=self.workspace_store.read(agent.workspace_path, filename),
            agent_version=agent.version,
        )

    async def update_file(
        self, agent_id: str, filename: str, payload: WorkspaceFileUpdate
    ) -> WorkspaceFileResponse:
        agent = await self._entity(agent_id)
        self._check_version(agent, payload.expected_version)
        previous_content = self.workspace_store.write(
            agent.workspace_path, filename, payload.content
        )
        agent.version += 1
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self.workspace_store.write(agent.workspace_path, filename, previous_content)
            raise
        return await self.get_file(agent_id, filename)

    async def _entity(self, agent_id: str) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        return agent

    async def _validate_model(self, provider_id: str, model_id: str) -> None:
        model = await self.session.scalar(
            select(ProviderModel)
            .join(Provider, Provider.id == ProviderModel.provider_id)
            .where(
                ProviderModel.id == model_id,
                ProviderModel.provider_id == provider_id,
                ProviderModel.enabled.is_(True),
                Provider.enabled.is_(True),
            )
        )
        if model is None:
            raise AgentConfigurationError(
                "Selected enabled Model does not belong to the enabled Provider"
            )

    @staticmethod
    def _check_version(agent: Agent, expected_version: int) -> None:
        if agent.version != expected_version:
            raise AgentConflictError(
                "Agent was changed by another request; "
                f"current version is {agent.version}"
            )

    def _cleanup_create(
        self, staging: Path | None, final_directory: Path | None
    ) -> None:
        if staging is not None and staging.exists():
            self.workspace_store.purge(staging)
        if final_directory is not None and final_directory.exists():
            self.workspace_store.purge(final_directory)

    @staticmethod
    def _response_query(agent_id: str | None = None):
        query = (
            select(Agent, Provider.name, ProviderModel.model_name)
            .join(Provider, Provider.id == Agent.provider_id)
            .join(ProviderModel, ProviderModel.id == Agent.model_id)
        )
        return query.where(Agent.id == agent_id) if agent_id else query

    @staticmethod
    def _response(agent: Agent, provider_name: str, model_name: str) -> AgentResponse:
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            status=agent.status,
            workspace_path=agent.workspace_path,
            provider_id=agent.provider_id,
            provider_name=provider_name,
            model_id=agent.model_id,
            model_name=model_name,
            is_coordinator=agent.is_coordinator,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )
