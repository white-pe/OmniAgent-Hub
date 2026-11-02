"""HTTP endpoints for knowledge document source versions."""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
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
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge.storage import (
    KnowledgeFileEmptyError,
    KnowledgeFileTooLargeError,
    LocalKnowledgeFileStore,
)
from pawteam_api.knowledge.parsing import (
    KnowledgeDocumentParseResultNotReadyError,
    KnowledgeDocumentParsingConflictError,
    KnowledgeDocumentParsingFailedError,
    KnowledgeParsingService,
)

from pawteam_api.knowledge_schemas import (
    KnowledgeDocumentParseResultResponse,
    KnowledgeDocumentVersionResponse,
)

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

async def get_knowledge_parsing_service(
    request: Request,
) -> KnowledgeParsingService:
    """获取当前应用实例的解析 Service，不在依赖中创建数据库会话。"""

    return request.app.state.knowledge_parsing_service


ParsingServiceDependency = Annotated[
    KnowledgeParsingService,
    Depends(get_knowledge_parsing_service),
]


def translate_parsing_error(error: Exception) -> HTTPException:
    """统一转换解析接口错误，避免两个端点维护不同的错误规则。"""

    if isinstance(error, KnowledgeDocumentVersionNotFoundError):
        return HTTPException(
            status_code=404,
            detail="Document version not found",
        )

    if isinstance(error, KnowledgeDocumentParseResultNotReadyError):
        return HTTPException(
            status_code=409,
            detail="Parse result is not available",
        )

    if isinstance(error, KnowledgeDocumentParsingConflictError):
        return HTTPException(
            status_code=409,
            detail=str(error),
        )

    if isinstance(error, KnowledgeDocumentParsingFailedError):
        # 该异常表示 Service 已保存 parse_failed 和错误原因。
        # 本轮统一用 422 表达“本次源文件处理未成功”。
        return HTTPException(
            status_code=422,
            detail=str(error),
        )

    # 未预期故障需要记录堆栈，但不能向客户端返回绝对路径、
    # SQL 内容或底层异常字符串。
    logger.error(
        "Unexpected knowledge parsing failure",
        exc_info=(type(error), error, error.__traceback__),
    )
    return HTTPException(
        status_code=500,
        detail="Knowledge parsing operation failed",
    )


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

@router.get(
    "/{document_id}/versions",
    response_model=list[KnowledgeDocumentVersionResponse],
)
async def list_document_versions(
    document_id: str,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeDocumentVersionResponse]:
    """分页返回版本元信息，不读取磁盘上的源文件。"""

    try:
        return await KnowledgeDocumentService(session).list_versions(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
    except KnowledgeDocumentNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        ) from error


@router.get(
    "/{document_id}/versions/{version_id}",
    response_model=KnowledgeDocumentVersionResponse,
)
async def get_document_version(
    document_id: str,
    version_id: str,
    session: SessionDependency,
) -> KnowledgeDocumentVersionResponse:
    """返回指定文档版本的元信息。"""

    try:
        return await KnowledgeDocumentService(session).get_version(
            document_id=document_id,
            version_id=version_id,
        )
    except KnowledgeDocumentNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        ) from error
    except KnowledgeDocumentVersionNotFoundError as error:
        # 版本不存在、版本属于其他文档，都返回相同的版本不存在响应。
        raise HTTPException(
            status_code=404,
            detail="Document version not found",
        ) from error


@router.post(
    "/{document_id}/versions/{version_id}/parse",
    response_model=KnowledgeDocumentParseResultResponse,
    status_code=status.HTTP_200_OK,
)
async def parse_document_version(
    document_id: str,
    version_id: str,
    parsing_service: ParsingServiceDependency,
) -> KnowledgeDocumentParseResultResponse:
    """执行解析；已经成功的版本返回已保存结果。"""

    try:
        return await parsing_service.parse_version(
            document_id=document_id,
            version_id=version_id,
        )
    except Exception as error:
        # 在 HTTP 边界转换错误，Service 保持不依赖 FastAPI。
        # 未预期错误会由转换函数记录堆栈并返回通用 500。
        raise translate_parsing_error(error) from error


@router.get(
    "/{document_id}/versions/{version_id}/parse-result",
    response_model=KnowledgeDocumentParseResultResponse,
)
async def get_document_parse_result(
    document_id: str,
    version_id: str,
    parsing_service: ParsingServiceDependency,
) -> KnowledgeDocumentParseResultResponse:
    """只查询已有结果，绝不隐式触发解析。"""

    try:
        return await parsing_service.get_result(
            document_id=document_id,
            version_id=version_id,
        )
    except Exception as error:
        raise translate_parsing_error(error) from error