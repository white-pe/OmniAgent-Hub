"""切块批次向量化接口。"""

import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from pawteam_api.knowledge.embedding_client import (
    EmbeddingRequestError,
    EmbeddingResponseError,
)
from pawteam_api.knowledge.embedding_persistence import (
    EmbeddingPersistenceConflictError,
    EmbeddingSourceNotFoundError,
    KnowledgeEmbeddingPersistenceService,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeEmbeddingExecutionResponse,
)
from pawteam_api.security.secret_store import SecretNotFoundError


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix=(
        "/knowledge-documents/{document_id}"
        "/versions/{version_id}"
        "/chunk-sets/{chunk_set_id}/embeddings"
    ),
    tags=["knowledge-embeddings"],
)


async def get_embedding_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """为当前请求提供客户端，请求处理结束后关闭连接。"""

    # 使用依赖注入，后续验证时可以替换为模拟客户端，
    # 不需要修改真实的向量化业务代码。
    async with httpx.AsyncClient() as client:
        yield client


@router.post(
    "/{profile_id}",
    response_model=KnowledgeEmbeddingExecutionResponse,
)
async def execute_embeddings(
    request: Request,
    document_id: UUID,
    version_id: UUID,
    chunk_set_id: UUID,
    profile_id: UUID,
    http_client: httpx.AsyncClient = Depends(get_embedding_http_client),
) -> KnowledgeEmbeddingExecutionResponse:
    """生成并保存整组向量；已有完整有效结果时直接复用。"""

    try:
        # 只传入 Session 工厂，不在路由中打开数据库事务。
        # Service 自己负责：
        # 读取来源 → 关闭读取会话 → 调用模型 → 开启写入事务。
        service = KnowledgeEmbeddingPersistenceService(
            session_factory=request.app.state.session_factory,
            secret_store=request.app.state.secret_store,
            http_client=http_client,
            batch_size=request.app.state.settings.knowledge_embedding_batch_size,
        )

        # UUID 路径参数先由 FastAPI 校验，再转成数据库使用的字符串。
        # 同时传入全部父资源 ID，由 Service 检查资源归属。
        result = await service.embed_chunk_set(
            document_id=str(document_id),
            version_id=str(version_id),
            chunk_set_id=str(chunk_set_id),
            profile_id=str(profile_id),
        )

    except EmbeddingSourceNotFoundError as error:
        # 包括批次不存在、父资源关系不匹配、Profile 不存在。
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except EmbeddingPersistenceConflictError as error:
        # 例如 Provider 已禁用、配置发生变化、已有向量不完整。
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except SecretNotFoundError as error:
        # 此异常内容包含内部密钥引用，不能直接返回 str(error)。
        raise HTTPException(
            status_code=409,
            detail="Provider API key is missing; update provider credentials",
        ) from error

    except (EmbeddingRequestError, EmbeddingResponseError) as error:
        # 模型连接失败、超时、HTTP 失败或返回向量不合法，
        # 都属于本平台调用上游服务失败。
        # 客户端已对异常信息脱敏，不返回上游响应正文。
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    except ValueError as error:
        # 当前服务用 ValueError 表达内容或配置校验失败。
        # 不把这些内部校验信息原样暴露给调用方。
        raise HTTPException(
            status_code=409,
            detail=(
                "Chunk content or embedding configuration is invalid; "
                "inspect limits and profile settings"
            ),
        ) from error

    except Exception as error:
        # 未预期错误记录完整服务端堆栈，响应只提供通用说明。
        logger.exception(
            "Embedding execution failed: profile_id=%s chunk_set_id=%s",
            profile_id,
            chunk_set_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Embedding execution failed; inspect server logs",
        ) from error

    # 放在业务异常处理之外：
    # 如果响应模型与 Service 返回结构不一致，应暴露为程序错误，
    # 不能误判为用户的内容或配置冲突。
    return KnowledgeEmbeddingExecutionResponse.model_validate(result)
