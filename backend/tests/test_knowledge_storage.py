from io import BytesIO
from pathlib import Path
from uuid import uuid4

import hashlib
import pytest

from pawteam_api.config import Settings
from pawteam_api.knowledge.storage import (
    InvalidKnowledgeFileIdentityError,
    KnowledgeFileAlreadyExistsError,
    KnowledgeFileEmptyError,
    KnowledgeFileTooLargeError,
    LocalKnowledgeFileStore,
    KnowledgeFileIntegrityError,
    KnowledgeFileNotFoundError,
    KnowledgeFileReadLimitError,
)


def make_settings(
    data_dir: Path,
    max_upload_bytes: int = 1024,
    max_read_bytes: int = 1024,
) -> Settings:
    """测试分别设置上传和读取限制，避免依赖本机环境配置。"""

    return Settings(
        environment="test",
        data_dir=data_dir,
        secrets_dir=data_dir / "secrets",
        workspaces_dir=data_dir / "workspaces",
        database_url=f"sqlite+aiosqlite:///{data_dir / 'test.db'}",
        knowledge_max_upload_bytes=max_upload_bytes,
        knowledge_max_read_bytes=max_read_bytes,
    )


def test_store_streams_file_and_returns_metadata(tmp_path: Path) -> None:
    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    document_id = str(uuid4())
    version_id = str(uuid4())
    content = b"Example knowledge document"

    stored = store.save(document_id, version_id, BytesIO(content))

    path = store.root / stored.storage_key
    assert path.read_bytes() == content
    assert stored.size_bytes == len(content)
    assert len(stored.sha256) == 64
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_store_rejects_file_over_size_limit(tmp_path: Path) -> None:
    store = LocalKnowledgeFileStore(make_settings(tmp_path, max_upload_bytes=4))

    with pytest.raises(KnowledgeFileTooLargeError):
        store.save(str(uuid4()), str(uuid4()), BytesIO(b"12345"))

    assert not list(store.root.rglob("*.bin"))
    assert not list(store.root.rglob(".upload-*.tmp"))


def test_store_rejects_empty_file(tmp_path: Path) -> None:
    store = LocalKnowledgeFileStore(make_settings(tmp_path))

    with pytest.raises(KnowledgeFileEmptyError):
        store.save(str(uuid4()), str(uuid4()), BytesIO(b""))


def test_store_does_not_overwrite_existing_version(tmp_path: Path) -> None:
    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    document_id = str(uuid4())
    version_id = str(uuid4())

    store.save(document_id, version_id, BytesIO(b"original"))

    with pytest.raises(KnowledgeFileAlreadyExistsError):
        store.save(document_id, version_id, BytesIO(b"replacement"))

    path = store.root / "documents" / document_id / f"{version_id}.bin"
    assert path.read_bytes() == b"original"


def test_store_rejects_non_uuid_identity(tmp_path: Path) -> None:
    store = LocalKnowledgeFileStore(make_settings(tmp_path))

    with pytest.raises(InvalidKnowledgeFileIdentityError):
        store.save("../outside", str(uuid4()), BytesIO(b"content"))


def test_read_verified_returns_original_bytes(tmp_path: Path) -> None:
    """合法文件能够读取，降低上传上限也不影响已有文件。"""

    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    content = b"original source"
    stored = store.save(str(uuid4()), str(uuid4()), BytesIO(content))

    # 模拟上传策略调整：现在只允许上传 1 字节，
    # 但读取策略仍允许处理原来的文件。
    reader = LocalKnowledgeFileStore(
        make_settings(tmp_path, max_upload_bytes=1)
    )
    result = reader.read_verified(
        stored.storage_key,
        stored.size_bytes,
        stored.sha256,
    )

    assert result == content


def test_read_verified_detects_same_size_changes(tmp_path: Path) -> None:
    """相同大小的内容替换，也必须被摘要检查发现。"""

    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    stored = store.save(str(uuid4()), str(uuid4()), BytesIO(b"first"))

    # 只在测试里直接修改业务文件，模拟文件损坏。
    (store.root / stored.storage_key).write_bytes(b"other")

    with pytest.raises(KnowledgeFileIntegrityError, match="SHA-256"):
        store.read_verified(
            stored.storage_key,
            stored.size_bytes,
            stored.sha256,
        )


@pytest.mark.parametrize("replacement", [b"ab", b"abcdef"])
def test_read_verified_detects_size_changes(
    tmp_path: Path,
    replacement: bytes,
) -> None:
    """分别模拟文件被截断和追加内容。"""

    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    stored = store.save(str(uuid4()), str(uuid4()), BytesIO(b"abcd"))
    (store.root / stored.storage_key).write_bytes(replacement)

    with pytest.raises(KnowledgeFileIntegrityError):
        store.read_verified(
            stored.storage_key,
            stored.size_bytes,
            stored.sha256,
        )


def test_read_verified_reports_missing_file(tmp_path: Path) -> None:
    """元数据仍在，但源文件缺失时返回明确异常。"""

    store = LocalKnowledgeFileStore(make_settings(tmp_path))
    stored = store.save(str(uuid4()), str(uuid4()), BytesIO(b"content"))
    store.delete(stored.storage_key)

    with pytest.raises(KnowledgeFileNotFoundError):
        store.read_verified(
            stored.storage_key,
            stored.size_bytes,
            stored.sha256,
        )


def test_read_verified_enforces_read_limit(tmp_path: Path) -> None:
    """允许上传的文件，也可能超过本次完整读取的内存策略。"""

    store = LocalKnowledgeFileStore(
        make_settings(tmp_path, max_read_bytes=4)
    )
    stored = store.save(str(uuid4()), str(uuid4()), BytesIO(b"12345"))

    with pytest.raises(KnowledgeFileReadLimitError):
        store.read_verified(
            stored.storage_key,
            stored.size_bytes,
            stored.sha256,
        )


@pytest.mark.parametrize(
    "storage_key",
    [
        "documents/../../outside.bin",
        "/tmp/outside.bin",
    ],
)
def test_read_verified_rejects_unsafe_paths(
    tmp_path: Path,
    storage_key: str,
) -> None:
    """读取也必须执行路径检查，不能因为 key 来自内部就跳过。"""

    store = LocalKnowledgeFileStore(make_settings(tmp_path))

    with pytest.raises(ValueError):
        store.read_verified(
            storage_key,
            expected_size=1,
            expected_sha256=hashlib.sha256(b"x").hexdigest(),
        )