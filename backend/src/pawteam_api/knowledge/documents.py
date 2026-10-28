"""Business operations for knowledge documents and source versions."""

from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from anyio import to_thread

from pawteam_api.knowledge.storage import (
    LocalKnowledgeFileStore,
    StoredKnowledgeFile,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
    KnowledgeDocumentVersionResponse,
)
from pawteam_api.models import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)


class KnowledgeDocumentKnowledgeBaseNotFoundError(LookupError):
    """Raised when a document's knowledge base does not exist."""


class KnowledgeDocumentNotFoundError(LookupError):
    """Raised when the requested document does not exist."""


class KnowledgeDocumentFilenameError(ValueError):
    """Raised when the uploaded filename is invalid."""


class KnowledgeDocumentVersionConflictError(ValueError):
    """Raised when a concurrent upload creates the same version number."""


class KnowledgeDocumentUploadCleanupError(RuntimeError):
    """Raised when a failed database write cannot clean up its file."""


class KnowledgeDocumentMediaTypeError(ValueError):
    """上传方提供的 MIME 类型不符合元数据约束。"""


class KnowledgeDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> list[KnowledgeDocumentResponse]:
        """列出一个知识库下的所有逻辑文档。"""

        # 先确认知识库存在。
        # 否则“空列表”会掩盖调用方传错 ID 的问题。
        await self._require_knowledge_base(knowledge_base_id)

        documents = (
            await self.session.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_base_id == knowledge_base_id
                )
                .order_by(
                    KnowledgeDocument.created_at.desc(),
                    KnowledgeDocument.title,
                )
            )
        ).all()

        return [self._document_response(document) for document in documents]

    async def create(
        self,
        knowledge_base_id: str,
        payload: KnowledgeDocumentCreate,
    ) -> KnowledgeDocumentResponse:
        """创建逻辑文档，但不创建文件版本。"""

        await self._require_knowledge_base(knowledge_base_id)

        document = KnowledgeDocument(
            id=str(uuid4()),
            knowledge_base_id=knowledge_base_id,
            title=payload.title,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)

        return self._document_response(document)

    async def upload_version(
        self,
        document_id: str,
        source: BinaryIO,
        original_filename: str | None,
        media_type: str | None,
        file_store: LocalKnowledgeFileStore,
    ) -> KnowledgeDocumentVersionResponse:
        """保存一个不可变的文档版本。

        事务顺序如下：

        1. 确认逻辑文档存在。
        2. 计算下一个版本号。
        3. 生成版本 UUID。
        4. 将文件写入本地存储并计算摘要。
        5. 创建数据库版本记录。
        6. 数据库失败时删除已经写入的文件。
        """

        await self._require_document(document_id)

        normalized_filename = self._normalize_filename(original_filename)
        normalized_media_type = self._normalize_media_type(media_type)

        # 版本号由服务端分配，客户端不能直接提交版本号。
        # max(None) 表示当前还没有版本，因此从 1 开始。
        latest_version = await self.session.scalar(
            select(func.max(KnowledgeDocumentVersion.version_number)).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        )
        version_number = (latest_version or 0) + 1

        # 版本 ID 在写文件前生成。
        # storage.save() 会使用它构造不可变 storage_key。
        version_id = str(uuid4())

        # 文件存储层负责：
        # - 流式读取
        # - 文件大小限制
        # - SHA-256 计算
        # - 临时文件写入
        # - 原子发布
        # save() 内部包含同步读取、磁盘写入、fsync 和哈希计算。
        # 将整个存储操作放进工作线程，数据库操作仍留在当前异步任务。
        # 这里使用位置参数，因为 run_sync() 的后续参数会传给 save()。
        stored = await to_thread.run_sync(
            file_store.save,
            document_id,
            version_id,
            source,
        )

        try:
            version = KnowledgeDocumentVersion(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                original_filename=normalized_filename,
                media_type=normalized_media_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                storage_key=stored.storage_key,
                status="uploaded",
            )

            self.session.add(version)
            await self.session.commit()

        except IntegrityError as error:
            # 两个请求可能同时读到相同的 latest_version。
            # 数据库唯一约束会阻止重复版本号。
            await self.session.rollback()

            await self._cleanup_uploaded_file(
                file_store=file_store,
                stored=stored,
            )

            raise KnowledgeDocumentVersionConflictError(
                "Document version changed; retry the upload"
            ) from error

        except Exception:
            # 数据库发生其他异常时，也必须回滚事务并删除文件。
            # 否则磁盘上会出现没有数据库记录的孤立文件。
            await self.session.rollback()

            await self._cleanup_uploaded_file(
                file_store=file_store,
                stored=stored,
            )

            # 保留原始异常，让上层决定如何记录和转换。
            raise

        # commit 成功后再 refresh，确保返回数据库最终生成的时间字段。
        await self.session.refresh(version)

        return self._version_response(version)

    async def _require_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> None:
        """确认知识库存在。"""

        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
        )
        if knowledge_base is None:
            raise KnowledgeDocumentKnowledgeBaseNotFoundError(
                knowledge_base_id
            )

    async def _require_document(
        self,
        document_id: str,
    ) -> KnowledgeDocument:
        """获取文档，不存在时抛出明确异常。"""

        document = await self.session.get(
            KnowledgeDocument,
            document_id,
        )
        if document is None:
            raise KnowledgeDocumentNotFoundError(document_id)

        return document

    @staticmethod
    def _normalize_filename(
        original_filename: str | None,
    ) -> str:
        """清理上传方提供的文件名。

        文件名只作为展示和审计信息保存，绝不参与存储路径拼接。
        """

        if original_filename is None:
            raise KnowledgeDocumentFilenameError(
                "Uploaded file must have a filename"
            )

        # 浏览器和不同操作系统可能提交不同格式的路径分隔符。
        # 这里只保留最后一个路径片段，防止保存类似 ../../secret.txt。
        filename = original_filename.replace("\\", "/").rsplit("/", 1)[-1]
        filename = filename.strip()

        if not filename or filename in {".", ".."}:
            raise KnowledgeDocumentFilenameError(
                "Uploaded filename cannot be empty"
            )

        if len(filename) > 500:
            raise KnowledgeDocumentFilenameError(
                "Uploaded filename is too long"
            )

        return filename

    @staticmethod
    def _normalize_media_type(
        media_type: str | None,
    ) -> str | None:
        """规范化 MIME 类型，但不在这一层强行限制文件格式。"""

        if media_type is None:
            return None

        normalized = media_type.strip()
        if not normalized:
            return None

        if len(normalized) > 200:
            # 使用明确的业务异常，HTTP 层才能只捕获预期的输入错误。
            # 不应把所有 ValueError 都转成 400，以免掩盖程序缺陷。
            raise KnowledgeDocumentMediaTypeError("Media type is too long")

        return normalized

    @staticmethod
    async def _cleanup_uploaded_file(
            file_store: LocalKnowledgeFileStore,
            stored: StoredKnowledgeFile,
    ) -> None:
        """数据库写入失败后，异步等待文件清理完成。"""

        try:
            # 删除文件也是同步磁盘操作，同样交给工作线程。
            await to_thread.run_sync(
                file_store.delete,
                stored.storage_key,
            )
        except OSError as error:
            # 清理失败要明确上报，不能假装数据库与磁盘已经恢复一致。
            raise KnowledgeDocumentUploadCleanupError(
                f"Failed to clean up {stored.storage_key}"
            ) from error


    @staticmethod
    def _document_response(
        document: KnowledgeDocument,
    ) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            title=document.title,
            status=document.status,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    @staticmethod
    def _version_response(
        version: KnowledgeDocumentVersion,
    ) -> KnowledgeDocumentVersionResponse:
        return KnowledgeDocumentVersionResponse(
            id=version.id,
            document_id=version.document_id,
            version_number=version.version_number,
            original_filename=version.original_filename,
            media_type=version.media_type,
            size_bytes=version.size_bytes,
            sha256=version.sha256,
            status=version.status,
            error_message=version.error_message,
            created_at=version.created_at,
            updated_at=version.updated_at,
        )