"""HTTP endpoints for vector indexing and saved task state."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import (
    ResponseHandlingException,
    UnexpectedResponse,
)

from pawteam_api.knowledge.chunk_queries import (
    KnowledgeChunkQueryService,
    KnowledgeChunkSetNotFoundError,
)
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge.index_state import (
    VectorIndexBusyError,
    VectorIndexLeaseLostError,
)
from pawteam_api.knowledge.indexing import (
    KnowledgeVectorIndexingService,
    VectorIndexSourceError,
)
from pawteam_api.knowledge.vector_store import (
    QdrantVectorStore,
    VectorCollectionConflictError,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeVectorIndexExecutionResponse,
    KnowledgeVectorIndexResponse,
)
from pawteam_api.models import (
    KnowledgeEmbeddingProfile,
    KnowledgeVectorIndex,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix=(
        "/knowledge-documents/{document_id}"
        "/versions/{version_id}"
        "/chunk-sets/{chunk_set_id}/indexes"
    ),
    tags=["knowledge-indexes"],
)


async def require_source(
    request: Request,
    document_id: UUID,
    version_id: UUID,
    chunk_set_id: UUID,
    profile_id: UUID,
) -> int:
    """检查完整资源归属和 Profile，返回预期向量维度。"""

    async with request.app.state.session_factory() as session:
        try:
            # 复用已有查询服务，检查 document → version → chunk_set。
            # 不能只检查批次 ID，否则 URL 中的父资源约束会失效。
            await KnowledgeChunkQueryService(session).get_chunk_set(
                str(document_id),
                str(version_id),
                str(chunk_set_id),
            )
        except (
            KnowledgeDocumentVersionNotFoundError,
            KnowledgeChunkSetNotFoundError,
        ) as error:
            raise HTTPException(
                status_code=404,
                detail="Chunk set not found under this document version",
            ) from error

        profile = await session.get(
            KnowledgeEmbeddingProfile,
            str(profile_id),
        )
        if profile is None:
            raise HTTPException(
                status_code=404,
                detail="Embedding profile not found",
            )

        # 只返回普通值，不把 ORM 对象带出 Session。
        return profile.dimensions


@router.get(
    "/{profile_id}",
    response_model=KnowledgeVectorIndexResponse | None,
)
async def get_index_state(
    request: Request,
    document_id: UUID,
    version_id: UUID,
    chunk_set_id: UUID,
    profile_id: UUID,
) -> KnowledgeVectorIndexResponse | None:
    """只读取状态；尚无任务记录时返回 null，不隐式创建任务。"""

    await require_source(
        request, document_id, version_id, chunk_set_id, profile_id
    )

    async with request.app.state.session_factory() as session:
        record = await session.get(
            KnowledgeVectorIndex,
            (str(profile_id), str(chunk_set_id)),
        )

        if record is None:
            return None

        return KnowledgeVectorIndexResponse.model_validate(record)


@router.post(
    "/{profile_id}",
    response_model=KnowledgeVectorIndexExecutionResponse,
)
async def execute_index(
    request: Request,
    document_id: UUID,
    version_id: UUID,
    chunk_set_id: UUID,
    profile_id: UUID,
) -> KnowledgeVectorIndexExecutionResponse:
    """执行索引；失败任务再次调用即可重试，完成任务直接复用。"""

    dimensions = await require_source(
        request, document_id, version_id, chunk_set_id, profile_id
    )

    # 当前采用请求内执行，每次请求独立创建并关闭客户端。
    # 地址只读取服务端配置，不允许请求方传入任意 Qdrant 地址。
    client = AsyncQdrantClient(
        url=request.app.state.settings.qdrant_url,
        timeout=10,
        api_key=(
            request.app.state.settings.qdrant_api_key.get_secret_value()
            if request.app.state.settings.qdrant_api_key else None
        ),
    )

    try:
        store = QdrantVectorStore(
            client=client,
            profile_id=str(profile_id),
            dimensions=dimensions,
        )
        service = KnowledgeVectorIndexingService(
            session_factory=request.app.state.session_factory,
            vector_store=store,
        )

        # require_source() 的读取 Session 此时已经关闭。
        # 实际执行仍由 Service 控制数据库事务、租约及分批写入。
        result = await service.index_chunk_set(
            profile_id=str(profile_id),
            chunk_set_id=str(chunk_set_id),
        )
        return KnowledgeVectorIndexExecutionResponse.model_validate(result)

    except (
        VectorIndexBusyError,
        VectorIndexLeaseLostError,
        VectorIndexSourceError,
        VectorCollectionConflictError,
    ) as error:
        # 正在执行、租约失效、来源不完整、集合不兼容，
        # 都需要调用方先检查状态或配置。
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail=(
                "Vector indexing timed out; "
                "inspect index state before retrying"
            ),
        ) from error

    except (ResponseHandlingException, UnexpectedResponse) as error:
        # 不把 Qdrant 的原始响应或连接详情暴露给前端。
        raise HTTPException(
            status_code=502,
            detail=(
                "Qdrant request failed; "
                "inspect service availability and index state"
            ),
        ) from error

    except Exception as error:
        # 未预期错误保留服务器日志；响应仅返回通用摘要。
        logger.exception(
            "Knowledge indexing failed: profile_id=%s chunk_set_id=%s",
            profile_id,
            chunk_set_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Vector indexing failed; inspect index state",
        ) from error

    finally:
        await client.close()
