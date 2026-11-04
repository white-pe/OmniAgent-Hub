from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy import delete, func, select

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.knowledge.indexing import (
    KnowledgeVectorIndexingService,
    VectorIndexSourceError,
)
from pawteam_api.knowledge.vector_store import QdrantVectorStore
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


@pytest.fixture
async def indexing_environment(tmp_path: Path):
    """构造真实 SQLite 数据和内存 Qdrant，隔离外部模型与网络。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'indexing.db'}",
    )
    engine = create_database_engine(settings)

    # 每个测试都新建独立 schema，避免依赖本机数据库状态。
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = create_session_factory(engine)

    # 使用内存 Qdrant 快速验证 Adapter 和 Indexing Service 的协作。
    # 真实 Docker Qdrant 的 smoke test 会在测试命令中单独执行。
    qdrant = AsyncQdrantClient(location=":memory:")
    profile_id = str(uuid4())
    vector_store = QdrantVectorStore(
        client=qdrant,
        profile_id=profile_id,
        dimensions=2,
    )

    try:
        await vector_store.initialize()

        async with factory.begin() as session:
            provider = Provider(
                name="Indexing Test Provider",
                base_url="https://embedding.example/v1",
                api_key_ref=f"indexing-{uuid4().hex}",
            )
            knowledge_base = KnowledgeBase(name=f"Indexing KB {uuid4()}")
            session.add_all([provider, knowledge_base])
            await session.flush()

            document = KnowledgeDocument(
                knowledge_base_id=knowledge_base.id,
                title="Indexing Test Document",
            )
            session.add(document)
            await session.flush()

            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version_number=1,
                original_filename="guide.txt",
                size_bytes=4,
                sha256="a" * 64,
                storage_key=f"test/{uuid4().hex}",
                status="parsed",
            )
            session.add(version)
            # 解析结果通过外键引用版本，先确保版本记录已插入。
            await session.flush()

            session.add(
                KnowledgeDocumentParseResult(
                    version_id=version.id,
                    text="abcd",
                    char_count=4,
                    source_format="txt",
                    parser_name="test",
                    parser_version="1",
                )
            )
            # 切块批次的外键指向解析结果，先插入解析结果。
            await session.flush()

            chunk_set = KnowledgeChunkSet(
                version_id=version.id,
                source_text_sha256="b" * 64,
                splitter_name="test",
                splitter_version="1",
                chunk_size=2,
                chunk_overlap=0,
            )
            profile = KnowledgeEmbeddingProfile(
                id=profile_id,
                provider_id=provider.id,
                base_url=provider.base_url,
                model_name="test-embedding",
                model_revision="test-1",
                dimensions=2,
                send_dimensions=False,
                input_policy_version="raw-v1",
            )
            session.add_all([chunk_set, profile])
            await session.flush()

            chunks = [
                KnowledgeChunk(
                    chunk_set_id=chunk_set.id,
                    chunk_index=index,
                    text=text,
                    char_count=2,
                    start_char=index * 2,
                    end_char=index * 2 + 2,
                )
                for index, text in enumerate(("ab", "cd"))
            ]
            session.add_all(chunks)
            await session.flush()

            # 使用方向不同的向量，便于确认写入结果与来源片段一致。
            session.add_all(
                [
                    KnowledgeChunkEmbedding(
                        profile_id=profile.id,
                        chunk_id=chunks[0].id,
                        vector=[1.0, 0.0],
                    ),
                    KnowledgeChunkEmbedding(
                        profile_id=profile.id,
                        chunk_id=chunks[1].id,
                        vector=[0.0, 1.0],
                    ),
                ]
            )

            ids = {
                "profile_id": profile.id,
                "chunk_set_id": chunk_set.id,
                "knowledge_base_id": knowledge_base.id,
                "document_id": document.id,
                "chunk_ids": [chunk.id for chunk in chunks],
            }

        service = KnowledgeVectorIndexingService(
            session_factory=factory,
            vector_store=vector_store,
        )
        yield factory, service, vector_store, ids
    finally:
        # 清理测试专属集合和客户端，不影响其他测试数据。
        if await qdrant.collection_exists(vector_store.collection_name):
            await qdrant.delete_collection(vector_store.collection_name)
        await qdrant.close()
        await engine.dispose()


async def indexed_point_count(vector_store: QdrantVectorStore) -> int:
    """精确统计当前测试集合中的点数。"""

    result = await vector_store.client.count(
        collection_name=vector_store.collection_name,
        exact=True,
    )
    return result.count


async def test_indexes_complete_chunk_set_and_reuses_point_ids(
    indexing_environment,
) -> None:
    """完整向量集可以写入；重复执行不会产生重复点。"""

    _, service, vector_store, ids = indexing_environment

    first = await service.index_chunk_set(
        profile_id=ids["profile_id"],
        chunk_set_id=ids["chunk_set_id"],
    )

    assert first.point_count == 2
    assert await indexed_point_count(vector_store) == 2

    # 同一切块批次再次同步应使用 chunk UUID 覆盖原点，而非新增点。
    second = await service.index_chunk_set(
        profile_id=ids["profile_id"],
        chunk_set_id=ids["chunk_set_id"],
    )

    assert second.point_count == 2
    assert await indexed_point_count(vector_store) == 2

    # 搜索结果应带有数据库中的文档和知识库关联信息。
    hits = await vector_store.search(
        vector=[1.0, 0.0],
        allowed_knowledge_base_ids=[ids["knowledge_base_id"]],
        limit=10,
    )
    assert str(hits[0].metadata.chunk_id) == ids["chunk_ids"][0]
    assert str(hits[0].metadata.document_id) == ids["document_id"]


async def test_missing_embedding_rejects_entire_index_operation(
    indexing_environment,
) -> None:
    """只要批次缺一个向量，就不能把剩余片段写进 Qdrant。"""

    factory, service, vector_store, ids = indexing_environment

    # 删除一个向量，制造“切块完整但向量化不完整”的异常状态。
    async with factory.begin() as session:
        await session.execute(
            delete(KnowledgeChunkEmbedding).where(
                KnowledgeChunkEmbedding.profile_id == ids["profile_id"],
                KnowledgeChunkEmbedding.chunk_id == ids["chunk_ids"][1],
            )
        )

    with pytest.raises(
        VectorIndexSourceError,
        match="complete embedding set",
    ):
        await service.index_chunk_set(
            profile_id=ids["profile_id"],
            chunk_set_id=ids["chunk_set_id"],
        )

    assert await indexed_point_count(vector_store) == 0


async def test_wrong_profile_configuration_is_rejected(
    indexing_environment,
) -> None:
    """防止把数据库 Profile 的向量写入另一个 Profile 集合。"""

    factory, _, vector_store, ids = indexing_environment
    wrong_store = QdrantVectorStore(
        client=vector_store.client,
        profile_id=str(uuid4()),
        dimensions=2,
    )
    service = KnowledgeVectorIndexingService(
        session_factory=factory,
        vector_store=wrong_store,
    )

    with pytest.raises(
        VectorIndexSourceError,
        match="does not match embedding profile",
    ):
        await service.index_chunk_set(
            profile_id=ids["profile_id"],
            chunk_set_id=ids["chunk_set_id"],
        )

    # 配置检查发生在 Qdrant 写入前。
    assert await indexed_point_count(vector_store) == 0


async def test_partial_qdrant_failure_can_retry_idempotently(
    indexing_environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部分批次已写入后失败，重试整批仍能得到正确点数。"""

    _, service, vector_store, ids = indexing_environment

    # 将每次 upsert 限制为一个点，以稳定模拟第二批失败。
    vector_store.max_upsert_points = 1
    original_upsert = vector_store.upsert
    calls = 0

    async def fail_second_call(points) -> None:
        nonlocal calls
        calls += 1

        if calls == 2:
            raise OSError("simulated Qdrant outage")

        await original_upsert(points)

    monkeypatch.setattr(vector_store, "upsert", fail_second_call)

    with pytest.raises(OSError, match="simulated Qdrant outage"):
        await service.index_chunk_set(
            profile_id=ids["profile_id"],
            chunk_set_id=ids["chunk_set_id"],
        )

    # 第一批已成功，证明外部向量库不具备跨批次事务回滚。
    assert await indexed_point_count(vector_store) == 1

    # 恢复真实 upsert 后重新执行整个批次。
    # 第一个点按相同 UUID 覆盖，第二个点补齐。
    monkeypatch.setattr(vector_store, "upsert", original_upsert)
    result = await service.index_chunk_set(
        profile_id=ids["profile_id"],
        chunk_set_id=ids["chunk_set_id"],
    )

    assert result.point_count == 2
    assert await indexed_point_count(vector_store) == 2


async def test_invalid_stored_vector_is_rejected_before_qdrant_write(
    indexing_environment,
) -> None:
    """数据库里出现错误维度的向量时，必须在写入前失败。"""

    factory, service, vector_store, ids = indexing_environment

    async with factory.begin() as session:
        record = await session.get(
            KnowledgeChunkEmbedding,
            (ids["profile_id"], ids["chunk_ids"][0]),
        )
        assert record is not None
        record.vector = [1.0]

    with pytest.raises(
        VectorIndexSourceError,
        match="failed validation",
    ):
        await service.index_chunk_set(
            profile_id=ids["profile_id"],
            chunk_set_id=ids["chunk_set_id"],
        )

    assert await indexed_point_count(vector_store) == 0
