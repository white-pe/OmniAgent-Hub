import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pawteam_api.knowledge.bindings import (
    BindingConfigurationError,
    BindingConflictError,
    BindingNotFoundError,
    KnowledgeBaseBindingService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseBindingUpdate,
    KnowledgeBaseCreate,
)
from pawteam_api.knowledge.service import KnowledgeBaseService
from pawteam_api.models import Agent, Base, Provider, ProviderModel


def test_agent_knowledge_base_binding_lifecycle(tmp_path: Path) -> None:
    asyncio.run(_exercise_binding_service(tmp_path))


async def _exercise_binding_service(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'bindings.db'}",
    )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            provider_id = str(uuid4())
            model_id = str(uuid4())
            agent_id = str(uuid4())

            session.add(
                Provider(
                    id=provider_id,
                    name="Binding Test Provider",
                    base_url="https://example.com/v1",
                    api_key_ref="binding-test-provider",
                )
            )
            session.add(
                ProviderModel(
                    id=model_id,
                    provider_id=provider_id,
                    model_name="test-model",
                    display_name="Test Model",
                )
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="Binding Test Agent",
                    workspace_path="binding-test-agent",
                    provider_id=provider_id,
                    model_id=model_id,
                )
            )
            await session.commit()

            knowledge_base = await KnowledgeBaseService(session).create(
                KnowledgeBaseCreate(name="Engineering Docs")
            )
            service = KnowledgeBaseBindingService(session)

            assert await service.list_for_agent(agent_id) == []

            created = await service.create(agent_id, knowledge_base.id)
            assert created.agent_id == agent_id
            assert created.knowledge_base_id == knowledge_base.id
            assert created.knowledge_base_name == "Engineering Docs"
            assert created.enabled is True

            with pytest.raises(BindingConflictError):
                await service.create(agent_id, knowledge_base.id)

            disabled = await service.set_enabled(
                agent_id,
                knowledge_base.id,
                KnowledgeBaseBindingUpdate(enabled=False),
            )
            assert disabled.enabled is False

            enabled = await service.set_enabled(
                agent_id,
                knowledge_base.id,
                KnowledgeBaseBindingUpdate(enabled=True),
            )
            assert enabled.enabled is True

            bindings = await service.list_for_agent(agent_id)
            assert len(bindings) == 1
            assert bindings[0].knowledge_base_id == knowledge_base.id

            with pytest.raises(BindingConfigurationError):
                await service.list_for_agent("missing-agent")

            with pytest.raises(BindingConfigurationError):
                await service.create(agent_id, "missing-knowledge-base")

            await service.delete(agent_id, knowledge_base.id)
            assert await service.list_for_agent(agent_id) == []

            with pytest.raises(BindingNotFoundError):
                await service.delete(agent_id, knowledge_base.id)
    finally:
        await engine.dispose()