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
    KnowledgeChunkEmbedding,
    KnowledgeChunkSet,
    KnowledgeDocument,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
    Provider,
)


def make_profile(
    provider_id: str,
    *,
    revision: str = "1",
    dimensions: int = 2,
) -> KnowledgeEmbeddingProfile:
    """集中准备有效配置，测试只改变需要验证的字段。"""

    return KnowledgeEmbeddingProfile(
        provider_id=provider_id,
        base_url="https://embedding.example/v1",
        model_name="test-embedding",
        model_revision=revision,
        dimensions=dimensions,
        send_dimensions=False,
        input_policy_version="raw-v1",
    )


@pytest.fixture
async def embedding_session(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncSession, str, str, str]]:
    """建立真实外键关系，所有数据仅存在于临时数据库中。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'embeddings.db'}",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)
        async with factory() as session:
            provider = Provider(
                name="Embedding Test Provider",
                base_url="https://embedding.example/v1",
                api_key_ref="test-reference",
            )
            knowledge = KnowledgeBase(name="Embedding Model Docs")
            session.add_all([provider, knowledge])
            await session.flush()

            document = KnowledgeDocument(
                knowledge_base_id=knowledge.id,
                title="Guide",
            )
            session.add(document)
            await session.flush()

            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version_number=1,
                original_filename="guide.txt",
                size_bytes=5,
                sha256="0" * 64,
                storage_key="test-only",
                status="parsed",
            )
            session.add(version)
            await session.flush()

            session.add(
                KnowledgeDocumentParseResult(
                    version_id=version.id,
                    text="hello",
                    char_count=5,
                    source_format="txt",
                    parser_name="utf8-text",
                    parser_version="1",
                )
            )
            await session.flush()

            chunk_set = KnowledgeChunkSet(
                version_id=version.id,
                source_text_sha256="0" * 64,
                splitter_name="boundary-character",
                splitter_version="1",
                chunk_size=800,
                chunk_overlap=100,
            )
            session.add(chunk_set)
            await session.flush()

            chunk = KnowledgeChunk(
                chunk_set_id=chunk_set.id,
                chunk_index=0,
                text="hello",
                char_count=5,
                start_char=0,
                end_char=5,
            )
            profile = make_profile(provider.id)
            session.add_all([chunk, profile])
            await session.flush()

            session.add(
                KnowledgeChunkEmbedding(
                    profile_id=profile.id,
                    chunk_id=chunk.id,
                    vector=[1.0, 0.5],
                )
            )
            await session.commit()

            # 提取 ID，避免后续 rollback 导致 ORM 属性过期。
            yield session, provider.id, profile.id, chunk.id
    finally:
        await engine.dispose()


async def test_vector_round_trip(embedding_session) -> None:
    """验证向量与配置、片段的关联能够真实落库并重新读取。"""

    session, _, profile_id, chunk_id = embedding_session
    session.expire_all()

    record = await session.get(
        KnowledgeChunkEmbedding,
        (profile_id, chunk_id),
    )
    assert record is not None
    assert record.vector == [1.0, 0.5]


async def test_duplicate_profile_is_rejected(embedding_session) -> None:
    """完全相同的配置不应重复保存。"""

    session, provider_id, _, _ = embedding_session
    session.add(make_profile(provider_id))

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.parametrize("dimensions", [0, -1])
async def test_invalid_dimensions_are_rejected(
    embedding_session,
    dimensions: int,
) -> None:
    """数据库也要保证期望维度为正数。"""

    session, provider_id, _, _ = embedding_session
    session.add(make_profile(provider_id, dimensions=dimensions))

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_duplicate_chunk_vector_is_rejected(embedding_session) -> None:
    """同一配置和片段不能重复插入向量。"""

    session, _, profile_id, chunk_id = embedding_session
    session.add(
        KnowledgeChunkEmbedding(
            profile_id=profile_id,
            chunk_id=chunk_id,
            vector=[0.5, 1.0],
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_different_profiles_can_embed_same_chunk(embedding_session) -> None:
    """不同版本配置可以保存同一片段的独立向量。"""

    session, provider_id, _, chunk_id = embedding_session
    profile = make_profile(provider_id, revision="2")
    session.add(profile)
    await session.flush()

    session.add(
        KnowledgeChunkEmbedding(
            profile_id=profile.id,
            chunk_id=chunk_id,
            vector=[0.5, 1.0],
        )
    )
    await session.commit()

    count = await session.scalar(
        select(func.count())
        .select_from(KnowledgeChunkEmbedding)
        .where(KnowledgeChunkEmbedding.chunk_id == chunk_id)
    )
    assert count == 2


async def test_chunk_deletion_cleans_vectors(embedding_session) -> None:
    """删除片段时，数据库应级联删除关联向量。"""

    session, _, _, chunk_id = embedding_session
    await session.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
    )
    await session.commit()

    count = await session.scalar(
        select(func.count()).select_from(KnowledgeChunkEmbedding)
    )
    assert count == 0


@pytest.mark.parametrize("target", ["profile", "provider"])
async def test_referenced_configuration_cannot_be_deleted(
    embedding_session,
    target: str,
) -> None:
    """已被引用的配置或 Provider 不能直接删除。"""

    session, provider_id, profile_id, _ = embedding_session
    model = KnowledgeEmbeddingProfile if target == "profile" else Provider
    target_id = profile_id if target == "profile" else provider_id

    with pytest.raises(IntegrityError):
        await session.execute(delete(model).where(model.id == target_id))
        await session.commit()
    await session.rollback()


@pytest.mark.parametrize("missing", ["profile", "chunk"])
async def test_vector_requires_existing_parents(
    embedding_session,
    missing: str,
) -> None:
    """禁止保存引用不存在配置或片段的孤立向量。"""

    session, _, profile_id, chunk_id = embedding_session
    session.add(
        KnowledgeChunkEmbedding(
            profile_id="missing" if missing == "profile" else profile_id,
            chunk_id="missing" if missing == "chunk" else chunk_id,
            vector=[1.0, 0.5],
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()