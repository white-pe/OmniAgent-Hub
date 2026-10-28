import asyncio
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pawteam_api.config import Settings
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentFilenameError,
    KnowledgeDocumentService,
)
from pawteam_api.knowledge.service import KnowledgeBaseService
from pawteam_api.knowledge.storage import (
    KnowledgeFileEmptyError,
    LocalKnowledgeFileStore,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeDocumentCreate,
)
from pawteam_api.models import Base


def test_document_version_upload_lifecycle(tmp_path: Path) -> None:
    asyncio.run(_exercise_document_version_upload(tmp_path))


async def _exercise_document_version_upload(tmp_path: Path) -> None:
    """验证文档版本上传、版本号递增和文件元数据写入。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'versions.db'}",
        knowledge_max_upload_bytes=1024,
    )
    file_store = LocalKnowledgeFileStore(settings)
    engine = create_async_engine(settings.database_url)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            knowledge_base = await KnowledgeBaseService(session).create(
                KnowledgeBaseCreate(name="Version Docs"),
            )
            document = await KnowledgeDocumentService(session).create(
                knowledge_base.id,
                KnowledgeDocumentCreate(title="API Guide"),
            )

            service = KnowledgeDocumentService(session)

            first_content = b"first version"
            first = await service.upload_version(
                document_id=document.id,
                source=BytesIO(first_content),
                original_filename="guide.md",
                media_type="text/markdown",
                file_store=file_store,
            )

            assert first.document_id == document.id
            assert first.version_number == 1
            assert first.original_filename == "guide.md"
            assert first.media_type == "text/markdown"
            assert first.size_bytes == len(first_content)
            assert first.sha256 == hashlib.sha256(first_content).hexdigest()
            assert first.status == "uploaded"

            first_path = file_store.root / (
                "documents"
                f"/{document.id}/{first.id}.bin"
            )
            assert first_path.read_bytes() == first_content

            second = await service.upload_version(
                document_id=document.id,
                source=BytesIO(b"second version"),
                original_filename="guide-v2.md",
                media_type="text/markdown",
                file_store=file_store,
            )
            assert second.version_number == 2
            assert second.id != first.id

            with pytest.raises(KnowledgeFileEmptyError):
                await service.upload_version(
                    document_id=document.id,
                    source=BytesIO(b""),
                    original_filename="empty.md",
                    media_type="text/markdown",
                    file_store=file_store,
                )

            with pytest.raises(KnowledgeDocumentFilenameError):
                await service.upload_version(
                    document_id=document.id,
                    source=BytesIO(b"content"),
                    original_filename="   ",
                    media_type="text/plain",
                    file_store=file_store,
                )
    finally:
        await engine.dispose()