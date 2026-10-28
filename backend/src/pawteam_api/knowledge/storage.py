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
        destination = self.root / relative_key
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