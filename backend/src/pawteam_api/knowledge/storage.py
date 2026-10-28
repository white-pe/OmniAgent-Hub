"""Private, bounded, atomic storage for knowledge source files."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from pawteam_api.config import Settings

_CHUNK_SIZE = 1024 * 1024


class KnowledgeFileTooLargeError(ValueError):
    """Raised when a source file exceeds the configured size limit."""


class KnowledgeFileEmptyError(ValueError):
    """Raised when a source file has no content."""


class KnowledgeFileAlreadyExistsError(FileExistsError):
    """Raised when an immutable version's storage key already exists."""


class InvalidKnowledgeFileIdentityError(ValueError):
    """Raised when a document or version ID is not a UUID."""


@dataclass(frozen=True)
class StoredKnowledgeFile:
    storage_key: str
    size_bytes: int
    sha256: str


class LocalKnowledgeFileStore:
    def __init__(self, settings: Settings) -> None:
        self.root = (settings.data_dir / "knowledge-files").resolve()
        self.max_upload_bytes = settings.knowledge_max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def save(
        self,
        document_id: str,
        version_id: str,
        source: BinaryIO,
    ) -> StoredKnowledgeFile:
        document_id = self._canonical_uuid(document_id)
        version_id = self._canonical_uuid(version_id)

        relative_key = f"documents/{document_id}/{version_id}.bin"

        # 所有实际写入路径都通过统一方法生成，确保路径边界规则一致。
        destination = self._path_for_key(relative_key)
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(parent, 0o700)
        self._assert_inside_root(parent)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-",
            suffix=".tmp",
            dir=parent,
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with os.fdopen(descriptor, "wb") as target:
                while chunk := source.read(_CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > self.max_upload_bytes:
                        raise KnowledgeFileTooLargeError(
                            "File exceeds the configured upload size limit"
                        )
                    digest.update(chunk)
                    target.write(chunk)

                if size_bytes == 0:
                    raise KnowledgeFileEmptyError("File must not be empty")

                target.flush()
                os.fsync(target.fileno())

            os.chmod(temporary, 0o600)

            try:
                # A hard link publishes the complete file without replacing an
                # existing immutable version.
                os.link(temporary, destination)
            except FileExistsError as error:
                raise KnowledgeFileAlreadyExistsError(
                    "File already exists for this document version"
                ) from error

            return StoredKnowledgeFile(
                storage_key=relative_key,
                size_bytes=size_bytes,
                sha256=digest.hexdigest(),
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _assert_inside_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as error:
            raise ValueError("Knowledge file path escapes storage root") from error

    @staticmethod
    def _canonical_uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, AttributeError) as error:
            raise InvalidKnowledgeFileIdentityError(
                "Document and version IDs must be UUIDs"
            ) from error


    def delete(self, storage_key: str) -> None:
        """删除一个已经保存的知识库源文件。

        该方法只接受存储系统自己生成的相对 key，不接受绝对路径。
        这样可以避免调用方通过 storage_key 删除存储根目录之外的文件。
        """

        path = self._path_for_key(storage_key)

        # missing_ok=True 让清理动作具备幂等性：
        # 文件已经被删除时，不需要再次抛出异常。
        path.unlink(missing_ok=True)

    def _path_for_key(self, storage_key: str) -> Path:
        """把内部 storage key 安全转换为绝对路径。"""

        relative_path = Path(storage_key)

        # storage_key 理论上由 save() 生成，但这里仍然必须再次校验。
        # 不能因为当前调用方是内部 Service，就跳过边界检查。
        if (
            not storage_key
            or relative_path.is_absolute()
            or any(
                part in {"", ".", ".."}
                for part in relative_path.parts
            )
        ):
            raise ValueError("Invalid knowledge file storage key")

        # 删除接口只允许操作 documents 目录。
        # 即使未来 storage 根目录下增加其他类型文件，也不会被误删。
        if relative_path.parts[0] != "documents":
            raise ValueError("Storage key must point to a document file")

        path = (self.root / relative_path).resolve()
        self._assert_inside_root(path)

        return path