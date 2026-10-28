"""HTTP endpoints for knowledge document source versions."""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentFilenameError,
    KnowledgeDocumentMediaTypeError,
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentService,
    KnowledgeDocumentUploadCleanupError,
    KnowledgeDocumentVersionConflictError,
)
from pawteam_api.knowledge.storage import (
    KnowledgeFileEmptyError,
    KnowledgeFileTooLargeError,
    LocalKnowledgeFileStore,
)
from pawteam_api.knowledge_schemas import KnowledgeDocumentVersionResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/knowledge-documents",
    tags=["knowledge-documents"],
)

SessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]


def get_knowledge_file_store(request: Request) -> LocalKnowledgeFileStore:
    """从应用状态获取启动阶段创建的存储组件。"""

    return request.app.state.knowledge_file_store


FileStoreDependency = Annotated[
    LocalKnowledgeFileStore,
    Depends(get_knowledge_file_store),
]


@router.post(
    "/{document_id}/versions",
    response_model=KnowledgeDocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_version(
    document_id: str,
    session: SessionDependency,
    file_store: FileStoreDependency,
    file: Annotated[UploadFile, File()],
) -> KnowledgeDocumentVersionResponse:
    """接收一个上传文件，并创建对应的文档版本。"""

    try:
        # 直接传入文件对象，不调用 await file.read() 读取整个文件。
        # 文件名和 MIME 类型只用于记录；大小、摘要和路径由服务端生成。
        return await KnowledgeDocumentService(session).upload_version(
            document_id=document_id,
            source=file.file,
            original_filename=file.filename,
            media_type=file.content_type,
            file_store=file_store,
        )
    except KnowledgeDocumentNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        ) from error
    except KnowledgeFileTooLargeError as error:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the configured upload size limit",
        ) from error
    except (
        KnowledgeFileEmptyError,
        KnowledgeDocumentFilenameError,
        KnowledgeDocumentMediaTypeError,
    ) as error:
        # 这些是预期的用户输入问题，允许返回经过控制的错误说明。
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    except KnowledgeDocumentVersionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail="Document version changed; retry the upload",
        ) from error
    except (KnowledgeDocumentUploadCleanupError, OSError) as error:
        # 服务端日志保留完整堆栈。
        # HTTP 响应不暴露本机存储路径或操作系统错误细节。
        logger.exception(
            "Document version storage failed: document_id=%s",
            document_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Document upload failed",
        ) from error
    finally:
        # 成功或失败后，都释放上传文件持有的资源。
        # 数据库事务与业务文件清理由 Service 负责。
        await file.close()