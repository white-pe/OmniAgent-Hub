import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pawteam_api.knowledge.documents import (
    KnowledgeDocumentKnowledgeBaseNotFoundError,
    KnowledgeDocumentService,
)
from pawteam_api.knowledge.service import KnowledgeBaseService
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeDocumentCreate,
)
from pawteam_api.models import Base


def test_document_service_create_and_list(tmp_path: Path) -> None:
    asyncio.run(_exercise_document_service(tmp_path))


async def _exercise_document_service(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'documents.db'}",
    )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            knowledge_base = await KnowledgeBaseService(session).create(
                KnowledgeBaseCreate(name="Engineering Docs"),
            )
            service = KnowledgeDocumentService(session)

            assert await service.list_for_knowledge_base(
                knowledge_base.id
            ) == []

            created = await service.create(
                knowledge_base.id,
                KnowledgeDocumentCreate(title="  API Guide  "),
            )

            assert created.knowledge_base_id == knowledge_base.id
            assert created.title == "API Guide"
            assert created.status == "active"
            assert created.id

            documents = await service.list_for_knowledge_base(
                knowledge_base.id
            )
            assert len(documents) == 1
            assert documents[0].id == created.id

            with pytest.raises(KnowledgeDocumentKnowledgeBaseNotFoundError):
                await service.list_for_knowledge_base("missing-knowledge-base")

            with pytest.raises(KnowledgeDocumentKnowledgeBaseNotFoundError):
                await service.create(
                    "missing-knowledge-base",
                    KnowledgeDocumentCreate(title="Orphan Document"),
                )
    finally:
        await engine.dispose()