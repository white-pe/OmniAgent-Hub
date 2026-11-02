from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select
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
    KnowledgeDocument,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)


@pytest.fixture
async def version_session(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncSession, str]]:
    """为每个测试创建独立数据库，并准备一个源文件版本。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'parse-results.db'}",
    )

    # 必须使用项目的 engine 工厂：
    # 该工厂会开启 SQLite 外键检查，才能真实验证级联删除。
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)

        async with session_factory() as session:
            knowledge_base = KnowledgeBase(name="Parse Result Docs")
            session.add(knowledge_base)
            await session.flush()

            # 分阶段 flush，让父表记录和默认 UUID 先生成，
            # 再给子表设置外键，不依赖 ORM 自动推断插入顺序。
            document = KnowledgeDocument(
                knowledge_base_id=knowledge_base.id,
                title="Guide",
            )
            session.add(document)
            await session.flush()

            # 本测试只验证数据库模型，不读取真实文件。
            # 因此这里构造符合字段约束的版本元数据。
            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version_number=1,
                original_filename="guide.md",
                media_type="text/markdown",
                size_bytes=1,
                sha256="0" * 64,
                storage_key="test-only",
            )
            session.add(version)
            await session.commit()

            # 提前保存普通字符串，后续 rollback 不影响测试使用该 ID。
            version_id = version.id
            yield session, version_id

    finally:
        await engine.dispose()


def make_result(version_id: str) -> KnowledgeDocumentParseResult:
    """统一构造一份结果，避免多个测试重复填写相同字段。"""

    text = "# Guide\n正文\n"
    return KnowledgeDocumentParseResult(
        version_id=version_id,
        text=text,
        char_count=len(text),
        source_format="markdown",
        parser_name="utf8-text",
        parser_version="1",
    )


@pytest.mark.asyncio
async def test_parse_result_can_be_persisted(
    version_session: tuple[AsyncSession, str],
) -> None:
    """验证文本、字符数、解析器信息和数据库生成时间。"""

    session, version_id = version_session
    result = make_result(version_id)
    session.add(result)
    await session.commit()
    await session.refresh(result)

    assert result.text == "# Guide\n正文\n"
    assert result.char_count == len(result.text)
    assert result.source_format == "markdown"
    assert result.parser_name == "utf8-text"
    assert result.parser_version == "1"
    assert result.created_at is not None


@pytest.mark.asyncio
async def test_parse_result_rejects_duplicate_version(
    version_session: tuple[AsyncSession, str],
) -> None:
    """同一个源文件版本，不能插入第二份当前解析结果。"""

    session, version_id = version_session
    first = make_result(version_id)
    session.add(first)
    await session.commit()

    # 让第二次插入直接验证数据库主键约束，
    # 避免同一会话中已有对象引发 ORM 身份冲突提示。
    session.expunge(first)

    session.add(make_result(version_id))
    with pytest.raises(IntegrityError):
        await session.commit()

    # 提交失败后必须 rollback，才能继续使用这个会话。
    await session.rollback()


@pytest.mark.asyncio
async def test_deleting_version_removes_parse_result(
    version_session: tuple[AsyncSession, str],
) -> None:
    """验证数据库外键级联，不依赖 ORM relationship 删除。"""

    session, version_id = version_session
    session.add(make_result(version_id))
    await session.commit()

    await session.execute(
        delete(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.id == version_id
        )
    )
    await session.commit()

    # 重新执行 SELECT，检查数据库中确实已经没有关联结果。
    remaining = await session.scalar(
        select(KnowledgeDocumentParseResult).where(
            KnowledgeDocumentParseResult.version_id == version_id
        )
    )
    assert remaining is None