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


class KnowledgeFileNotFoundError(FileNotFoundError):
    """版本记录存在，但对应源文件已经缺失。"""


class KnowledgeFileIntegrityError(ValueError):
    """源文件的实际大小或摘要与版本记录不一致。"""


class KnowledgeFileReadLimitError(ValueError):
    """文件超过当前组件允许完整读入内存的大小。"""


@dataclass(frozen=True)
class StoredKnowledgeFile:
    storage_key: str
    size_bytes: int
    sha256: str


class LocalKnowledgeFileStore:
    def __init__(self, settings: Settings) -> None:
        self.root = (settings.data_dir / "knowledge-files").resolve()
        self.max_upload_bytes = settings.knowledge_max_upload_bytes
        self.max_read_bytes = settings.knowledge_max_read_bytes
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


    def read_verified(
        self,
        storage_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes:
        """读取源文件，只有大小和摘要都匹配时才返回内容。

        参数应来自数据库中的版本记录，不能直接信任客户端提交的值。
        本方法不修改文件，也不更新数据库状态。
        """

        # 上传流程不允许空文件，因此版本记录中的大小必须大于零。
        # 这里发现非法元数据就立即停止，避免继续执行错误的读取。
        if expected_size < 1:
            raise ValueError("Expected file size must be positive")

        # save() 生成的是 64 位小写十六进制 SHA-256 字符串。
        # 先检查格式，可以区分“元数据格式错误”和“文件内容不匹配”。
        if (
            len(expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_sha256
            )
        ):
            raise ValueError("Expected SHA-256 must be lowercase hexadecimal")

        # 在读取前检查上限，避免依据过大的版本记录分配大量内存。
        if expected_size > self.max_read_bytes:
            raise KnowledgeFileReadLimitError(
                "File exceeds the configured read size limit"
            )

        # 复用保存和删除时的路径检查，拒绝越出存储根目录的 key。
        path = self._path_for_key(storage_key)
        digest = hashlib.sha256()
        content = bytearray()

        try:
            # 使用二进制模式，不在存储层解码或转换换行符。
            # 摘要必须对应上传时保存的原始字节。
            with path.open("rb") as source:
                while True:
                    # 最多读取“预期大小 + 1”个字节。
                    # 多读出的一个字节用于判断文件是否被追加内容，
                    # 避免文件异常变大时一直读取到文件末尾。
                    read_size = min(
                        _CHUNK_SIZE,
                        expected_size - len(content) + 1,
                    )
                    chunk = source.read(read_size)

                    if not chunk:
                        break

                    if len(content) + len(chunk) > expected_size:
                        raise KnowledgeFileIntegrityError(
                            "File is larger than its recorded size"
                        )

                    digest.update(chunk)
                    content.extend(chunk)

        except FileNotFoundError as error:
            # 只转换文件不存在的错误。
            # 权限不足、磁盘 I/O 错误等仍保留原始异常，便于定位原因。
            raise KnowledgeFileNotFoundError(
                "Knowledge source file does not exist"
            ) from error

        # 文件被截断或替换成更小的文件，会在这里被识别。
        if len(content) != expected_size:
            raise KnowledgeFileIntegrityError(
                "File size does not match its recorded size"
            )

        # 大小相同也不能说明内容相同，还必须核对摘要。
        if digest.hexdigest() != expected_sha256:
            raise KnowledgeFileIntegrityError(
                "File SHA-256 does not match its recorded digest"
            )

        # 返回本次已经完成校验的内容，后续解析器直接使用它，
        # 不要校验后再次打开路径读取，以免拿到另一份内容。
        return bytes(content)