import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pawteam_api.config import Settings
from pawteam_api.database import create_database_engine
from pawteam_api.main import create_app
from pawteam_api.models import Base


async def create_test_schema(settings: Settings) -> None:
    """测试使用独立数据库，避免读写本地开发数据。"""

    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def upload_api(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    """每个测试创建独立知识库、文档和应用实例。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        workspaces_dir=tmp_path / "workspaces",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'upload.db'}",
        # 使用很小的限制，便于测试边界，无需构造大文件。
        knowledge_max_upload_bytes=64,
    )
    asyncio.run(create_test_schema(settings))

    with TestClient(create_app(settings)) as client:
        knowledge_response = client.post(
            "/api/knowledge-bases",
            json={"name": "Upload API Docs"},
        )
        assert knowledge_response.status_code == 201
        knowledge_id = knowledge_response.json()["id"]

        document_response = client.post(
            f"/api/knowledge-bases/{knowledge_id}/documents",
            json={"title": "API Guide"},
        )
        assert document_response.status_code == 201
        document_id = document_response.json()["id"]

        yield client, f"/api/knowledge-documents/{document_id}/versions"


def test_upload_creates_versions(
    upload_api: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    client, path = upload_api
    content = b"# API Guide"

    first = client.post(
        path,
        files={"file": ("guide.md", content, "text/markdown")},
    )
    assert first.status_code == 201
    version = first.json()

    assert version["version_number"] == 1
    assert version["original_filename"] == "guide.md"
    assert version["size_bytes"] == len(content)
    assert version["sha256"] == hashlib.sha256(content).hexdigest()
    assert version["status"] == "uploaded"
    assert "storage_key" not in version

    # 除了验证响应，还验证磁盘上的内容确实与上传内容一致。
    stored_path = (
        tmp_path
        / "knowledge-files"
        / "documents"
        / version["document_id"]
        / f"{version['id']}.bin"
    )
    assert stored_path.read_bytes() == content

    second = client.post(
        path,
        files={"file": ("guide.md", b"updated", "text/markdown")},
    )
    assert second.status_code == 201
    assert second.json()["version_number"] == 2
    assert second.json()["id"] != version["id"]


@pytest.mark.parametrize(
    ("filename", "content", "media_type", "expected_status"),
    [
        ("empty.md", b"", "text/markdown", 400),
        ("large.md", b"x" * 65, "text/markdown", 413),
        ("x" * 501, b"content", "text/plain", 400),
        ("guide.md", b"content", "x" * 201, 400),
    ],
)
def test_upload_rejects_invalid_input(
    upload_api: tuple[TestClient, str],
    tmp_path: Path,
    filename: str,
    content: bytes,
    media_type: str,
    expected_status: int,
) -> None:
    client, path = upload_api

    response = client.post(
        path,
        files={"file": (filename, content, media_type)},
    )
    assert response.status_code == expected_status

    # 失败请求不应留下已发布文件或上传临时文件。
    root = tmp_path / "knowledge-files"
    assert not list(root.rglob("*.bin"))
    assert not list(root.rglob(".upload-*.tmp"))


def test_upload_requires_document_and_file(
    upload_api: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    client, path = upload_api

    missing_document = client.post(
        "/api/knowledge-documents/missing-id/versions",
        files={"file": ("guide.md", b"content", "text/markdown")},
    )
    assert missing_document.status_code == 404

    # 字段名必须叫 file，缺少该字段交给 FastAPI 请求校验处理。
    missing_file = client.post(path, data={"note": "no file"})
    assert missing_file.status_code == 422

    assert not list((tmp_path / "knowledge-files").rglob("*.bin"))