import os
from dataclasses import replace
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient, models

from pawteam_api.knowledge.vector_store import (
    QdrantVectorStore,
    VectorCollectionConflictError,
    VectorIndexPoint,
    VectorMetadata,
)


@pytest.fixture
async def vector_environment():
    """默认用内存模式，也允许显式连接本机 Docker 服务。"""

    url = os.environ.get("OMNIAGENT_TEST_QDRANT_URL")

    if url:
        client = AsyncQdrantClient(url=url, timeout=10)
    else:
        client = AsyncQdrantClient(location=":memory:")

    # 每个测试使用新 Profile，因此集合名称也唯一。
    # 远程测试只清理自己创建的集合。
    store = QdrantVectorStore(
        client=client,
        profile_id=str(uuid4()),
        dimensions=2,
    )

    try:
        await store.initialize()
        yield client, store
    finally:
        try:
            if await client.collection_exists(store.collection_name):
                await client.delete_collection(store.collection_name)
        finally:
            await client.close()


def make_point(
    store: QdrantVectorStore,
    knowledge_id,
    vector: tuple[float, ...],
    *,
    document_id=None,
) -> VectorIndexPoint:
    """构造独立、有效的关联信息。"""

    return VectorIndexPoint(
        metadata=VectorMetadata(
            profile_id=store.profile_id,
            knowledge_base_id=knowledge_id,
            document_id=document_id or uuid4(),
            version_id=uuid4(),
            chunk_set_id=uuid4(),
            chunk_id=uuid4(),
        ),
        vector=vector,
    )


async def test_repeated_upsert_updates_same_point(vector_environment) -> None:
    """重复写入不能增加点数，修改向量后仍使用同一个点 ID。"""

    client, store = vector_environment
    point = make_point(store, uuid4(), (1.0, 0.0))

    await store.initialize()
    await store.upsert([point])
    await store.upsert([replace(point, vector=(0.0, 1.0))])

    count = await client.count(
        collection_name=store.collection_name,
        exact=True,
    )
    assert count.count == 1

    saved = await client.retrieve(
        collection_name=store.collection_name,
        ids=[str(point.metadata.chunk_id)],
        with_vectors=True,
    )
    assert saved[0].vector == pytest.approx([0.0, 1.0])


async def test_search_filters_knowledge_scope(vector_environment) -> None:
    """其他知识库即使相似度更高，也不能进入允许范围的结果。"""

    _, store = vector_environment
    allowed_id, other_id = uuid4(), uuid4()

    first = make_point(store, allowed_id, (0.8, 0.2))
    second = make_point(store, allowed_id, (0.0, 1.0))
    forbidden = make_point(store, other_id, (1.0, 0.0))

    await store.upsert([first, second, forbidden])

    hits = await store.search(
        vector=[1.0, 0.0],
        allowed_knowledge_base_ids=[str(allowed_id)],
    )

    assert len(hits) == 2
    assert hits[0].metadata.chunk_id == first.metadata.chunk_id
    assert all(
        hit.metadata.knowledge_base_id == allowed_id
        for hit in hits
    )


async def test_empty_scope_never_queries(
    vector_environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空授权集合必须直接返回，不能退化为无过滤搜索。"""

    client, store = vector_environment

    async def unexpected_query(*args, **kwargs):
        pytest.fail("Empty scope unexpectedly queried Qdrant")

    monkeypatch.setattr(client, "query_points", unexpected_query)

    assert await store.search(
        vector=[1.0, 0.0],
        allowed_knowledge_base_ids=[],
    ) == []


@pytest.mark.parametrize("mismatch", ["dimensions", "distance"])
async def test_collection_mismatch_is_rejected(
    vector_environment,
    mismatch: str,
) -> None:
    """集合不兼容时应报错，不能自动删除后重建。"""

    client, store = vector_environment

    if mismatch == "dimensions":
        incompatible = QdrantVectorStore(
            client=client,
            profile_id=str(store.profile_id),
            dimensions=3,
        )
    else:
        # 仅重建当前测试自己的临时集合。
        await client.delete_collection(store.collection_name)
        await client.create_collection(
            collection_name=store.collection_name,
            vectors_config=models.VectorParams(
                size=2,
                distance=models.Distance.DOT,
            ),
        )
        incompatible = store

    with pytest.raises(VectorCollectionConflictError):
        await incompatible.initialize()


async def test_duplicate_ids_do_not_write(vector_environment) -> None:
    client, store = vector_environment
    point = make_point(store, uuid4(), (1.0, 0.0))

    with pytest.raises(ValueError, match="Duplicate"):
        await store.upsert([point, point])

    count = await client.count(store.collection_name, exact=True)
    assert count.count == 0


async def test_invalid_vector_does_not_partially_write(
    vector_environment,
) -> None:
    """本批后面的向量无效，前面的点也不应被写入。"""

    client, store = vector_environment
    good = make_point(store, uuid4(), (1.0, 0.0))
    bad = make_point(store, uuid4(), (0.0, 0.0))

    with pytest.raises(ValueError):
        await store.upsert([good, bad])

    count = await client.count(store.collection_name, exact=True)
    assert count.count == 0


async def test_another_profile_is_rejected(vector_environment) -> None:
    client, store = vector_environment
    point = make_point(store, uuid4(), (1.0, 0.0))
    wrong = VectorIndexPoint(
        metadata=point.metadata.model_copy(
            update={"profile_id": uuid4()}
        ),
        vector=point.vector,
    )

    with pytest.raises(ValueError, match="another embedding profile"):
        await store.upsert([wrong])

    assert (await client.count(store.collection_name, exact=True)).count == 0


async def test_delete_document_preserves_other_documents(
    vector_environment,
) -> None:
    _, store = vector_environment
    knowledge_id = uuid4()
    document_id = uuid4()

    removed = make_point(
        store,
        knowledge_id,
        (1.0, 0.0),
        document_id=document_id,
    )
    retained = make_point(store, knowledge_id, (0.0, 1.0))

    await store.upsert([removed, retained])
    await store.delete_document(
        knowledge_base_id=str(knowledge_id),
        document_id=str(document_id),
    )

    hits = await store.search(
        vector=[1.0, 0.0],
        allowed_knowledge_base_ids=[str(knowledge_id)],
    )
    assert [hit.metadata.chunk_id for hit in hits] == [
        retained.metadata.chunk_id
    ]


async def test_search_rejects_wrong_dimensions(vector_environment) -> None:
    _, store = vector_environment

    with pytest.raises(ValueError):
        await store.search(
            vector=[1.0],
            allowed_knowledge_base_ids=[str(uuid4())],
        )