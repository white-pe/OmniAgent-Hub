import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.models import (
    Base,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeChunkSet,
    KnowledgeDocument,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)


def make_chunk_set(version_id: str) -> KnowledgeChunkSet:
    """固定配置用于验证批次的去重约束。"""

    return KnowledgeChunkSet(
        version_id=version_id,
        source_text_sha256=hashlib.sha256(
            b"hello world"
        ).hexdigest(),
        splitter_name="recursive-character",
        splitter_version="1",
        chunk_size=800,
        chunk_overlap=100,
    )


def make_chunk(chunk_set_id: str) -> KnowledgeChunk:
    """准备一个对应原文 [0:5] 的有效片段。"""

    return KnowledgeChunk(
        chunk_set_id=chunk_set_id,
        chunk_index=0,
        text="hello",
        char_count=5,
        start_char=0,
        end_char=5,
    )


@pytest.fixture
async def chunk_session(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncSession, str, str]]:
    """创建完整父子记录，验证真实外键和约束。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'chunks.db'}",
    )
    # 使用项目工厂，确保 SQLite 外键检查已经开启。
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)

        async with factory() as session:
            knowledge = KnowledgeBase(name="Chunk Test Docs")
            session.add(knowledge)
            await session.flush()

            document = KnowledgeDocument(
                knowledge_base_id=knowledge.id,
                title="Guide",
            )
            session.add(document)
            await session.flush()

            # 本轮只测数据库，不读写源文件。
            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version_number=1,
                original_filename="guide.txt",
                media_type="text/plain",
                size_bytes=11,
                sha256=hashlib.sha256(b"hello world").hexdigest(),
                storage_key="test-only",
                status="parsed",
            )
            session.add(version)
            await session.flush()

            session.add(
                KnowledgeDocumentParseResult(
                    version_id=version.id,
                    text="hello world",
                    char_count=11,
                    source_format="txt",
                    parser_name="utf8-text",
                    parser_version="1",
                )
            )
            await session.flush()

            chunk_set = make_chunk_set(version.id)
            session.add(chunk_set)
            await session.flush()

            session.add(make_chunk(chunk_set.id))
            await session.commit()

            # 提前提取字符串，避免测试中的 rollback 影响 ID 读取。
            version_id = version.id
            chunk_set_id = chunk_set.id
            yield session, version_id, chunk_set_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_chunks_persist_and_follow_version_deletion(
    chunk_session: tuple[AsyncSession, str, str],
) -> None:
    """验证片段入库，以及删除版本后的多层级联清理。"""

    session, version_id, chunk_set_id = chunk_session

    chunk = await session.scalar(
        select(KnowledgeChunk).where(
            KnowledgeChunk.chunk_set_id == chunk_set_id
        )
    )
    assert chunk is not None
    assert chunk.text == "hello"
    assert chunk.char_count == chunk.end_char - chunk.start_char

    await session.execute(
        delete(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.id == version_id
        )
    )
    await session.commit()

    # 版本 -> 解析结果 -> 批次 -> 片段，应全部级联删除。
    for model in (
        KnowledgeDocumentParseResult,
        KnowledgeChunkSet,
        KnowledgeChunk,
    ):
        count = await session.scalar(
            select(func.count()).select_from(model)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_duplicate_chunk_configuration_is_rejected(
    chunk_session: tuple[AsyncSession, str, str],
) -> None:
    """同一文本、同一参数不能重复保存一份批次。"""

    session, version_id, _ = chunk_session
    session.add(make_chunk_set(version_id))

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_duplicate_chunk_index_is_rejected(
    chunk_session: tuple[AsyncSession, str, str],
) -> None:
    """同一批次里的片段序号不能重复。"""

    session, _, chunk_set_id = chunk_session
    session.add(make_chunk(chunk_set_id))

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunk_size", 0),
        ("chunk_overlap", -1),
        ("chunk_overlap", 800),
    ],
)
async def test_invalid_chunk_configuration_is_rejected(
    chunk_session: tuple[AsyncSession, str, str],
    field: str,
    value: int,
) -> None:
    """长度必须为正，重叠必须在 [0, chunk_size) 内。"""

    session, version_id, _ = chunk_session
    chunk_set = make_chunk_set(version_id)
    setattr(chunk_set, field, value)
    session.add(chunk_set)

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunk_index", -1),
        ("end_char", 0),
        ("char_count", 99),
    ],
)
async def test_invalid_chunk_positions_are_rejected(
    chunk_session: tuple[AsyncSession, str, str],
    field: str,
    value: int,
) -> None:
    """片段序号、区间及长度必须满足基本一致性约束。"""

    session, _, chunk_set_id = chunk_session
    chunk = make_chunk(chunk_set_id)

    # 使用未占用的序号，避免重复序号掩盖本次要测试的约束。
    chunk.chunk_index = 1
    setattr(chunk, field, value)
    session.add(chunk)

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()