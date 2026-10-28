from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from pawteam_api.config import Settings
from pawteam_api.knowledge.storage import (
    InvalidKnowledgeFileIdentityError,
    KnowledgeFileAlreadyExistsError,
    KnowledgeFileEmptyError,
    KnowledgeFileTooLargeError,
    LocalKnowledgeFileStore,
)


def make_settings(data_dir: Path, max_upload_bytes: int = 1024) -> Settings:
    return Settings(
        environment="test",
        data_dir=data_dir,
        secrets_dir=data_dir / "secrets",
        workspaces_dir=data_dir / "workspaces",
        database_url=f"sqlite+aiosqlite:///{data_dir / 'test.db'}",
        knowledge_max_upload_bytes=max_upload_bytes,
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