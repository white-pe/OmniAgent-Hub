import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.knowledge.chunk_service import KnowledgeChunkingService
from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig
from pawteam_api.main import create_app
from pawteam_api.models import Base


SOURCE_TEXT = "abcdefghijklmno"


async def create_test_schema(settings: Settings) -> None:
    """只在当前测试的临时数据库中建表。"""

    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def create_test_batches(
    settings: Settings,
    document_id: str,
    version_id: str,
) -> tuple[str, str]:
    """使用真实 Service 创建两组参数不同的批次。"""

    # 使用独立 Engine，并在同一个异步调用中创建和释放，
    # 避免将数据库连接跨 asyncio.run() 的事件循环复用。
    engine = create_database_engine(settings)
    try:
        service = KnowledgeChunkingService(create_session_factory(engine))
        first = await service.create_chunk_set(
            document_id,
            version_id,
            KnowledgeChunkingConfig(chunk_size=8, chunk_overlap=2),
        )
        second = await service.create_chunk_set(
            document_id,
            version_id,
            KnowledgeChunkingConfig(chunk_size=6, chunk_overlap=1),
        )
        return first.id, second.id
    finally:
        await engine.dispose()


@pytest.fixture
def chunk_api(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str, str, str]]:
    """返回客户端、版本路径和两个批次 ID。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'chunks-api.db'}",
    )
    asyncio.run(create_test_schema(settings))

    with TestClient(create_app(settings)) as client:
        knowledge = client.post(
            "/api/knowledge-bases",
            json={"name": "Chunk Query API Docs"},
        )
        assert knowledge.status_code == 201

        document = client.post(
            f"/api/knowledge-bases/{knowledge.json()['id']}/documents",
            json={"title": "Chunk Query Guide"},
        )
        assert document.status_code == 201
        document_id = document.json()["id"]

        uploaded = client.post(
            f"/api/knowledge-documents/{document_id}/versions",
            files={"file": ("guide.txt", SOURCE_TEXT.encode(), "text/plain")},
        )
        assert uploaded.status_code == 201
        version_id = uploaded.json()["id"]
        version_path = (
            f"/api/knowledge-documents/{document_id}/versions/{version_id}"
        )

        parsed = client.post(f"{version_path}/parse")
        assert parsed.status_code == 200

        first_id, second_id = asyncio.run(
            create_test_batches(settings, document_id, version_id)
        )
        yield client, version_path, first_id, second_id


def test_batch_list_and_detail(
    chunk_api: tuple[TestClient, str, str, str],
) -> None:
    """列表与详情只返回参数；批次分页顺序应保持一致。"""

    client, version_path, first_id, second_id = chunk_api
    path = f"{version_path}/chunk-sets"

    listed = client.get(path)
    assert listed.status_code == 200
    batches = listed.json()

    assert {item["id"] for item in batches} == {first_id, second_id}
    assert all("chunks" not in item for item in batches)

    # 不假设两个批次的创建时间一定不同，按实际排序检查分页。
    page = client.get(path, params={"limit": 1, "offset": 1})
    assert page.status_code == 200
    assert [item["id"] for item in page.json()] == [batches[1]["id"]]

    detail = client.get(f"{path}/{first_id}")
    assert detail.status_code == 200
    assert detail.json()["chunk_size"] == 8
    assert detail.json()["chunk_overlap"] == 2
    assert "chunks" not in detail.json()


def test_chunks_are_paginated_and_match_source(
    chunk_api: tuple[TestClient, str, str, str],
) -> None:
    """验证片段排序、字符位置，以及越过最后一页的行为。"""

    client, version_path, first_id, _ = chunk_api
    path = f"{version_path}/chunk-sets/{first_id}/chunks"

    response = client.get(path, params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    page = response.json()

    assert page["chunk_set_id"] == first_id
    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert len(page["items"]) == 1

    chunk = page["items"][0]
    assert chunk["chunk_index"] == 1
    assert chunk["text"] == SOURCE_TEXT[
        chunk["start_char"]:chunk["end_char"]
    ]

    beyond = client.get(path, params={"offset": 100})
    assert beyond.status_code == 200
    assert beyond.json()["total"] == 3
    assert beyond.json()["items"] == []


def test_queries_check_resource_membership(
    chunk_api: tuple[TestClient, str, str, str],
) -> None:
    """已有批次不能通过另一个版本的 URL 读取。"""

    client, version_path, first_id, _ = chunk_api

    # 上传同一文档的第二个版本；不解析、不切块。
    upload_path = version_path.rsplit("/", 1)[0]
    uploaded = client.post(
        upload_path,
        files={"file": ("second.txt", b"second version", "text/plain")},
    )
    assert uploaded.status_code == 201
    other_version_path = f"{upload_path}/{uploaded.json()['id']}"

    empty = client.get(f"{other_version_path}/chunk-sets")
    assert empty.status_code == 200
    assert empty.json() == []

    wrong_parent = f"{other_version_path}/chunk-sets/{first_id}"
    assert client.get(wrong_parent).status_code == 404
    assert client.get(f"{wrong_parent}/chunks").status_code == 404

    missing_batch = client.get(f"{version_path}/chunk-sets/missing")
    assert missing_batch.status_code == 404

    missing_version = client.get(f"{upload_path}/missing/chunk-sets")
    assert missing_version.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_queries_reject_invalid_pagination(
    chunk_api: tuple[TestClient, str, str, str],
    params: dict[str, int],
) -> None:
    """批次列表和片段列表使用一致的分页范围。"""

    client, version_path, first_id, _ = chunk_api
    path = f"{version_path}/chunk-sets"

    assert client.get(path, params=params).status_code == 422
    assert client.get(
        f"{path}/{first_id}/chunks",
        params=params,
    ).status_code == 422