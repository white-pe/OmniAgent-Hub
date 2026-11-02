import asyncio
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentService,
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge.parsers import KnowledgeTextParser
from pawteam_api.knowledge.parsing import (
    KnowledgeDocumentParsingFailedError,
    KnowledgeParsingService,
)
from pawteam_api.knowledge.service import KnowledgeBaseService
from pawteam_api.knowledge.storage import LocalKnowledgeFileStore
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeDocumentCreate,
)
from pawteam_api.models import (
    Base,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)

ParsingEnvironment = tuple[
    async_sessionmaker[AsyncSession],
    LocalKnowledgeFileStore,
    KnowledgeParsingService,
]


@pytest.fixture
async def parsing_environment(
    tmp_path: Path,
) -> AsyncIterator[ParsingEnvironment]:
    """每个测试使用自己的数据库和文件目录。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'parsing.db'}",
        knowledge_max_upload_bytes=1024,
        knowledge_max_read_bytes=1024,
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)
        store = LocalKnowledgeFileStore(settings)
        service = KnowledgeParsingService(
            factory,
            store,
            KnowledgeTextParser(),
        )

        yield factory, store, service
    finally:
        await engine.dispose()


async def upload_source(
    environment: ParsingEnvironment,
    content: bytes = b"# Guide\r\nbody",
    filename: str = "guide.md",
) -> tuple[str, str]:
    """复用真实上传 Service，准备带真实大小和哈希的源文件。"""

    factory, store, _ = environment

    async with factory() as session:
        knowledge_base = await KnowledgeBaseService(session).create(
            KnowledgeBaseCreate(name=f"Parse Docs {uuid4()}"),
        )
        document = await KnowledgeDocumentService(session).create(
            knowledge_base.id,
            KnowledgeDocumentCreate(title="Guide"),
        )
        version = await KnowledgeDocumentService(session).upload_version(
            document_id=document.id,
            source=BytesIO(content),
            original_filename=filename,
            media_type="text/plain",
            file_store=store,
        )

        return document.id, version.id


@pytest.mark.asyncio
async def test_parse_saves_result_and_reuses_it(
    parsing_environment: ParsingEnvironment,
) -> None:
    """验证成功入库，以及重复调用不重新读取源文件。"""

    factory, store, service = parsing_environment
    document_id, version_id = await upload_source(parsing_environment)

    result = await service.parse_version(document_id, version_id)
    assert result.text == "# Guide\nbody"
    assert result.char_count == len(result.text)
    assert result.parser_name == "utf8-text"
    assert result.parser_version == "1"

    async with factory() as session:
        version = await session.get(KnowledgeDocumentVersion, version_id)
        assert version is not None
        assert version.status == "parsed"
        assert version.error_message is None

        # 删除源文件，确认下一次调用使用已有结果。
        # 仅用于测试，不代表业务上允许随意删除源文件。
        store.delete(version.storage_key)

    repeated = await service.parse_version(document_id, version_id)
    assert repeated == result

    async with factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(KnowledgeDocumentParseResult)
        )
        assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["encoding", "blank", "unsupported", "missing", "corrupt"],
)
async def test_expected_failures_are_saved(
    parsing_environment: ParsingEnvironment,
    scenario: str,
) -> None:
    """预期失败必须保存状态和原因，且不能产生成功结果。"""

    factory, store, service = parsing_environment
    content = b"\xff" if scenario == "encoding" else b"content"
    if scenario == "blank":
        content = b"   "

    filename = "guide.pdf" if scenario == "unsupported" else "guide.md"
    document_id, version_id = await upload_source(
        parsing_environment,
        content=content,
        filename=filename,
    )

    async with factory() as session:
        version = await session.get(KnowledgeDocumentVersion, version_id)
        assert version is not None
        key = version.storage_key

    if scenario == "missing":
        store.delete(key)
    elif scenario == "corrupt":
        # 保持大小不变，专门触发 SHA-256 校验失败。
        (store.root / key).write_bytes(b"x" * len(content))

    with pytest.raises(KnowledgeDocumentParsingFailedError):
        await service.parse_version(document_id, version_id)

    # 用新会话读取，证明失败信息已经提交到数据库。
    async with factory() as session:
        version = await session.get(KnowledgeDocumentVersion, version_id)
        assert version is not None
        assert version.status == "parse_failed"
        assert version.error_message

        result = await session.get(
            KnowledgeDocumentParseResult,
            version_id,
        )
        assert result is None


@pytest.mark.asyncio
async def test_failed_parse_can_be_retried(
    parsing_environment: ParsingEnvironment,
) -> None:
    """调整读取策略后重试，成功时清除旧错误原因。"""

    factory, store, service = parsing_environment
    document_id, version_id = await upload_source(parsing_environment)

    store.max_read_bytes = 1
    with pytest.raises(KnowledgeDocumentParsingFailedError):
        await service.parse_version(document_id, version_id)

    # 不修改源文件和哈希，只修正导致失败的读取策略。
    store.max_read_bytes = 1024
    result = await service.parse_version(document_id, version_id)
    assert result.text == "# Guide\nbody"

    async with factory() as session:
        version = await session.get(KnowledgeDocumentVersion, version_id)
        assert version is not None
        assert version.status == "parsed"
        assert version.error_message is None


@pytest.mark.asyncio
async def test_result_insert_failure_rolls_back_status(
    parsing_environment: ParsingEnvironment,
) -> None:
    """模拟结果入库失败，状态更新必须一起回滚。"""

    factory, _, service = parsing_environment
    document_id, version_id = await upload_source(parsing_environment)

    def fail_insert(*args: object) -> None:
        raise RuntimeError("simulated result insert failure")

    # 临时在 INSERT 前注入异常；finally 必须移除，避免污染其他测试。
    event.listen(
        KnowledgeDocumentParseResult,
        "before_insert",
        fail_insert,
    )
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            await service.parse_version(document_id, version_id)
    finally:
        event.remove(
            KnowledgeDocumentParseResult,
            "before_insert",
            fail_insert,
        )

    async with factory() as session:
        version = await session.get(KnowledgeDocumentVersion, version_id)
        assert version is not None
        assert version.status == "uploaded"
        assert version.error_message is None

        result = await session.get(
            KnowledgeDocumentParseResult,
            version_id,
        )
        assert result is None


@pytest.mark.asyncio
async def test_parse_checks_document_membership(
    parsing_environment: ParsingEnvironment,
) -> None:
    """不能用其他文档的 ID 解析一个版本。"""

    _, _, service = parsing_environment
    _, version_id = await upload_source(parsing_environment)
    other_document_id, _ = await upload_source(parsing_environment)

    with pytest.raises(KnowledgeDocumentVersionNotFoundError):
        await service.parse_version(other_document_id, version_id)


@pytest.mark.asyncio
async def test_concurrent_calls_publish_one_result(
    parsing_environment: ParsingEnvironment,
) -> None:
    """并发调用最终只能发布一份结果，每次调用使用独立会话。"""

    factory, _, service = parsing_environment
    document_id, version_id = await upload_source(parsing_environment)

    first, second = await asyncio.gather(
        service.parse_version(document_id, version_id),
        service.parse_version(document_id, version_id),
    )
    assert first == second

    async with factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(KnowledgeDocumentParseResult)
        )
        assert count == 1