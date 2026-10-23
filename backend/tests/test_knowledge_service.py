
import asyncio
from pathlib import Path

import pytest
from pawteam_api.knowledge.service import (
    KnowledgeBaseConflictError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)
from pawteam_api.models import Base
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_knowledge_base_crud_and_version_conflicts(tmp_path: Path) -> None:
    asyncio.run(_exercise_knowledge_base_service(tmp_path))


async def _exercise_knowledge_base_service(tmp_path: Path) -> None:
    database_path = tmp_path / "knowledge.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
    )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            service = KnowledgeBaseService(session)

            created = await service.create(
                KnowledgeBaseCreate(
                    name="Engineering Docs",
                    description="Internal references",
                )
            )
            assert created.enabled is True
            assert created.version == 1
            assert len(await service.list()) == 1

            updated = await service.update(
                created.id,
                KnowledgeBaseUpdate(
                    expected_version=1,
                    description="",
                    enabled=False,
                ),
            )
            assert updated.description == ""
            assert updated.enabled is False
            assert updated.version == 2

            with pytest.raises(KnowledgeBaseConflictError):
                await service.update(
                    created.id,
                    KnowledgeBaseUpdate(
                        expected_version=1,
                        name="Stale Update",
                    ),
                )

            with pytest.raises(KnowledgeBaseConflictError):
                await service.create(
                    KnowledgeBaseCreate(name="Engineering Docs"),
                )

            with pytest.raises(KnowledgeBaseNotFoundError):
                await service.get("missing-id")

            with pytest.raises(KnowledgeBaseConflictError):
                await service.delete(created.id, expected_version=1)

            await service.delete(created.id, expected_version=2)

            with pytest.raises(KnowledgeBaseNotFoundError):
                await service.get(created.id)
    finally:
        await engine.dispose()