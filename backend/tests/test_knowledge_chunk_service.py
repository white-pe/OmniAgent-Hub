from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.knowledge.chunk_service import (
    KnowledgeChunkingService,
    KnowledgeChunkSourceNotReadyError,
)
from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig
from pawteam_api.models import (
    Base,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeChunkSet,
    KnowledgeDocument,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)


@pytest.fixture
async def chunk_service_environment(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], KnowledgeChunkingService]
]:
    """为每个测试创建独立数据库和 Service。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'chunk-service.db'}",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)
        yield factory, KnowledgeChunkingService(factory)
    finally:
        await engine.dispose()


async def create_parsed_source(
    factory: async_sessionmaker[AsyncSession],
    text: str,
    *,
    status: str = "parsed",
) -> tuple[str, str]:
    """建立符合模型关系的解析文本，不依赖文件上传流程。"""

    async with factory.begin() as session:
        knowledge_base = KnowledgeBase(
            name=f"Chunk Service Docs {text[:10]} {status}"
        )
        session.add(knowledge_base)
        await session.flush()

        document = KnowledgeDocument(
            knowledge_base_id=knowledge_base.id,
            title="Chunk Service Guide",
        )
        session.add(document)
        await session.flush()

        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_number=1,
            original_filename="guide.txt",
            media_type="text/plain",
            size_bytes=1,
            sha256="0" * 64,
            storage_key="test-only",
            status=status,
        )
        session.add(version)
        await session.flush()

        session.add(
            KnowledgeDocumentParseResult(
                version_id=version.id,
                text=text,
                char_count=len(text),
                source_format="txt",
                parser_name="utf8-text",
                parser_version="1",
            )
        )
        await session.flush()

        # 事务退出前提取普通字符串，避免 ORM 对象离开 Session 后过期。
        document_id = document.id
        version_id = version.id

    return document_id, version_id


@pytest.mark.asyncio
async def test_service_persists_batch_and_source_offsets(
    chunk_service_environment: tuple[
        async_sessionmaker[AsyncSession],
        KnowledgeChunkingService,
    ],
) -> None:
    """批次元数据、片段内容和字符区间必须完整对应解析文本。"""

    factory, service = chunk_service_environment
    source_text = "abcdefghijklmno"
    document_id, version_id = await create_parsed_source(
        factory,
        source_text,
    )

    result = await service.create_chunk_set(
        document_id,
        version_id,
        KnowledgeChunkingConfig(chunk_size=8, chunk_overlap=2),
    )

    assert result.version_id == version_id
    assert result.splitter_name == "boundary-character"
    assert result.splitter_version == "1"
    assert result.source_text_sha256
    assert [chunk.chunk_index for chunk in result.chunks] == [0, 1, 2]

    for chunk in result.chunks:
        assert chunk.text == source_text[chunk.start_char:chunk.end_char]
        assert chunk.char_count == len(chunk.text)
        assert chunk.char_count <= result.chunk_size


@pytest.mark.asyncio
async def test_same_configuration_reuses_existing_batch(
    chunk_service_environment: tuple[
        async_sessionmaker[AsyncSession],
        KnowledgeChunkingService,
    ],
) -> None:
    """同样的文本与配置重复请求返回同一个批次和片段 ID。"""

    factory, service = chunk_service_environment
    document_id, version_id = await create_parsed_source(
        factory,
        "a long enough text to generate several chunks",
    )
    config = KnowledgeChunkingConfig(chunk_size=12, chunk_overlap=3)

    first = await service.create_chunk_set(
        document_id,
        version_id,
        config,
    )
    repeated = await service.create_chunk_set(
        document_id,
        version_id,
        config,
    )

    assert repeated.id == first.id
    assert [chunk.id for chunk in repeated.chunks] == [
        chunk.id for chunk in first.chunks
    ]

    async with factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(KnowledgeChunkSet)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_different_configuration_creates_separate_batch(
    chunk_service_environment: tuple[
        async_sessionmaker[AsyncSession],
        KnowledgeChunkingService,
    ],
) -> None:
    """改变参数后应产生新批次，以便比较策略效果。"""

    _, service = chunk_service_environment
    document_id, version_id = await create_parsed_source(
        chunk_service_environment[0],
        "a long enough text to generate several chunks",
    )

    first = await service.create_chunk_set(
        document_id,
        version_id,
        KnowledgeChunkingConfig(chunk_size=12, chunk_overlap=2),
    )
    second = await service.create_chunk_set(
        document_id,
        version_id,
        KnowledgeChunkingConfig(chunk_size=10, chunk_overlap=2),
    )

    assert first.id != second.id
    assert first.chunk_size == 12
    assert second.chunk_size == 10


@pytest.mark.asyncio
async def test_service_rejects_version_that_is_not_parsed(
    chunk_service_environment: tuple[
        async_sessionmaker[AsyncSession],
        KnowledgeChunkingService,
    ],
) -> None:
    """上传完成但未解析的版本不能直接切块。"""

    factory, service = chunk_service_environment
    document_id, version_id = await create_parsed_source(
        factory,
        "not ready",
        status="uploaded",
    )

    with pytest.raises(KnowledgeChunkSourceNotReadyError):
        await service.create_chunk_set(
            document_id,
            version_id,
            KnowledgeChunkingConfig(chunk_size=8, chunk_overlap=2),
        )


@pytest.mark.asyncio
async def test_chunk_insert_failure_rolls_back_entire_batch(
    chunk_service_environment: tuple[
        async_sessionmaker[AsyncSession],
        KnowledgeChunkingService,
    ],
) -> None:
    """任意片段插入失败时，批次和片段都不能留下。"""

    factory, service = chunk_service_environment
    document_id, version_id = await create_parsed_source(
        factory,
        "a long enough text to create more than one chunk",
    )

    def fail_chunk_insert(
        mapper: object,
        connection: object,
        target: object,
    ) -> None:
        raise RuntimeError("simulated chunk insert failure")

    # 只在本测试期间注入失败，finally 中必须移除事件监听器。
    event.listen(
        KnowledgeChunk,
        "before_insert",
        fail_chunk_insert,
    )
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            await service.create_chunk_set(
                document_id,
                version_id,
                KnowledgeChunkingConfig(
                    chunk_size=12,
                    chunk_overlap=3,
                ),
            )
    finally:
        event.remove(
            KnowledgeChunk,
            "before_insert",
            fail_chunk_insert,
        )

    async with factory() as session:
        set_count = await session.scalar(
            select(func.count()).select_from(KnowledgeChunkSet)
        )
        chunk_count = await session.scalar(
            select(func.count()).select_from(KnowledgeChunk)
        )

        assert set_count == 0
        assert chunk_count == 0