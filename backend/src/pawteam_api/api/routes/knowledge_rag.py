"""受现有管理员认证/CSRF 保护的知识库工作台 API。"""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from pawteam_api.knowledge.embedding_client import EmbeddingRequestError, EmbeddingResponseError
from pawteam_api.knowledge.publication import PublicationConflictError, publish
from pawteam_api.knowledge.query_embedding import (
    QueryEmbeddingConfigurationError, QueryEmbeddingProfileNotFoundError,
)
from pawteam_api.knowledge.rag_schemas import (
    AnswerRequest, AnswerResponse, IngestionRequest, JobResponse, PublicationRequest,
    PublicationResponse, RetrievalRequest, RetrievalResponse,
)
from pawteam_api.knowledge.retrieval import RetrievalScopeError
from pawteam_api.knowledge.vector_store import QdrantVectorStore, VectorCollectionConflictError
from pawteam_api.models import (
    KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile, KnowledgeIngestionJob, KnowledgePublication,
    KnowledgeQueryHistory, KnowledgeQueryLog,
)
from pawteam_api.providers.client import ProviderRequestError
from pawteam_api.providers.service import (
    ProviderConflictError, ProviderModelNotFoundError, ProviderNotFoundError,
)
from pawteam_api.security.secret_store import SecretNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge-workbench"])


def factory(request):
    return request.app.state.session_factory


async def rag_operation(request: Request, payload, answer=False):
    try:
        async with asyncio.timeout(request.app.state.settings.knowledge_query_timeout_seconds):
            service = request.app.state.knowledge_retrieval_service
            return await (service.answer(payload) if answer else service.search(payload))
    except (RetrievalScopeError, QueryEmbeddingProfileNotFoundError) as error:
        raise HTTPException(404, detail=str(error)) from error
    except (
        QueryEmbeddingConfigurationError, VectorCollectionConflictError,
        ProviderConflictError, ProviderNotFoundError, ProviderModelNotFoundError,
    ) as error:
        raise HTTPException(409, detail=str(error)) from error
    except SecretNotFoundError as error:
        raise HTTPException(409, detail="模型密钥缺失，请更新 Provider") from error
    except TimeoutError as error:
        raise HTTPException(504, detail="检索或回答超时，请查看后台日志") from error
    except (EmbeddingRequestError, EmbeddingResponseError) as error:
        raise HTTPException(502, detail=str(error)) from error
    except (ResponseHandlingException, UnexpectedResponse, ProviderRequestError) as error:
        raise HTTPException(502, detail="模型服务或 Qdrant 不可用，请查看后台日志") from error
    except Exception as error:
        logger.exception("Knowledge query failed")
        raise HTTPException(500, detail="知识库查询失败，请查看后台日志") from error


@router.post("/knowledge/search", response_model=RetrievalResponse)
async def search(payload: RetrievalRequest, request: Request):
    return await rag_operation(request, payload)


@router.post("/knowledge/answer", response_model=AnswerResponse)
async def answer(payload: AnswerRequest, request: Request):
    return await rag_operation(request, payload, answer=True)


@router.get("/knowledge/audits")
async def audits(request: Request, limit: int = Query(50, ge=1, le=100),
                 offset: int = Query(0, ge=0)):
    async with factory(request)() as session:
        rows = (await session.scalars(select(KnowledgeQueryLog)
            .order_by(KnowledgeQueryLog.created_at.desc()).limit(limit).offset(offset))).all()
        return [{
            "id": row.id, "operation": row.operation, "status": row.status,
            "agent_id": row.agent_id, "latency_ms": row.latency_ms,
            "hit_count": row.hit_count, "created_at": row.created_at,
            "details": row.details_json,
        } for row in rows]


@router.get("/knowledge/history")
async def query_history(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """返回可还原的逐次问答快照；仅受管理员会话保护，不用于公开分享。"""

    async with factory(request)() as session:
        total = await session.scalar(
            select(func.count()).select_from(KnowledgeQueryHistory)
        )
        rows = (await session.execute(
            select(KnowledgeQueryHistory, KnowledgeQueryLog)
            .join(KnowledgeQueryLog, KnowledgeQueryLog.id == KnowledgeQueryHistory.request_id)
            .order_by(KnowledgeQueryHistory.created_at.desc())
            .limit(limit).offset(offset)
        )).all()
        items = [{
            "request_id": history.request_id,
            "query": history.query_text,
            "response": history.response_json,
            "operation": log.operation,
            "status": log.status,
            "agent_id": log.agent_id,
            "latency_ms": log.latency_ms,
            "hit_count": log.hit_count,
            "created_at": history.created_at,
        } for history, log in rows]
        return {"items": items, "total": total or 0}


@router.get("/knowledge/status")
async def rag_status(request: Request):
    remote_ok = False
    client = request.app.state.knowledge_retrieval_service.qdrant()
    try:
        async with asyncio.timeout(5):
            await client.get_collections()
        remote_ok = True
    except Exception:
        pass
    finally:
        await client.close()
    async with factory(request)() as session:
        counts = {}
        for name, model in (
            ("knowledge_bases", KnowledgeBase), ("documents", KnowledgeDocument),
            ("publications", KnowledgePublication),
        ):
            counts[name] = await session.scalar(select(func.count()).select_from(model))
        counts["active_jobs"] = await session.scalar(
            select(func.count()).select_from(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "running")))
        )
    return {"qdrant": "ok" if remote_ok else "unavailable", **counts}


@router.get("/knowledge/publications", response_model=list[PublicationResponse])
async def publications(request: Request, knowledge_base_id: UUID):
    async with factory(request)() as session:
        rows = (await session.scalars(select(KnowledgePublication)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgePublication.document_id)
            .where(KnowledgeDocument.knowledge_base_id == str(knowledge_base_id)))).all()
        return [PublicationResponse.model_validate(row) for row in rows]


@router.put("/knowledge-documents/{document_id}/publication", response_model=PublicationResponse)
async def publish_document(document_id: UUID, payload: PublicationRequest, request: Request):
    async with factory(request)() as session:
        profile = await session.get(KnowledgeEmbeddingProfile, str(payload.profile_id))
        if profile is None:
            raise HTTPException(404, detail="Profile not found")
        active = await session.scalar(select(KnowledgeIngestionJob.id).where(
            KnowledgeIngestionJob.active_key == str(document_id)
        ))
        if active:
            raise HTTPException(409, detail="文档正在处理，请等待任务完成")
        total = await session.scalar(select(func.count()).select_from(KnowledgeChunk)
            .where(KnowledgeChunk.chunk_set_id == str(payload.chunk_set_id)))
        dimensions = profile.dimensions
    client = request.app.state.knowledge_retrieval_service.qdrant()
    try:
        store = QdrantVectorStore(
            client=client, profile_id=str(payload.profile_id), dimensions=dimensions
        )
        if await store.count_chunk_set(str(payload.chunk_set_id)) != total or not total:
            raise HTTPException(409, detail="Qdrant 索引不完整，请提交重建任务")
    except (ResponseHandlingException, UnexpectedResponse, VectorCollectionConflictError) as error:
        raise HTTPException(409, detail="索引不可用，请检查 Qdrant 或重建索引") from error
    finally:
        await client.close()
    try:
        async with factory(request).begin() as session:
            return await publish(
                session, document_id=str(document_id),
                chunk_set_id=str(payload.chunk_set_id), profile_id=str(payload.profile_id),
            )
    except PublicationConflictError as error:
        raise HTTPException(409, detail=str(error)) from error


@router.delete("/knowledge-documents/{document_id}/publication", status_code=204)
async def unpublish(document_id: UUID, request: Request):
    async with factory(request).begin() as session:
        if await session.scalar(select(KnowledgeIngestionJob.id).where(
            KnowledgeIngestionJob.active_key == str(document_id)
        )):
            raise HTTPException(409, detail="请先取消或等待当前处理任务")
        await session.execute(delete(KnowledgePublication).where(
            KnowledgePublication.document_id == str(document_id)
        ))
    return Response(status_code=204)


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


@router.patch("/knowledge-documents/{document_id}")
async def update_document(document_id: UUID, payload: DocumentUpdate, request: Request):
    async with factory(request).begin() as session:
        document = await session.get(KnowledgeDocument, str(document_id))
        if document is None:
            raise HTTPException(404, detail="Document not found")
        if await session.scalar(select(KnowledgeIngestionJob.id).where(
            KnowledgeIngestionJob.active_key == document.id
        )):
            raise HTTPException(409, detail="文档正在处理，请稍后修改")
        if payload.title is not None:
            document.title = payload.title
        if payload.archived is not None:
            document.status = "archived" if payload.archived else "active"
    return {"id": str(document_id), "status": document.status, "title": document.title}


@router.get("/knowledge/jobs", response_model=list[JobResponse])
async def jobs(request: Request, document_id: UUID | None = None,
               limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    async with factory(request)() as session:
        statement = select(KnowledgeIngestionJob)
        if document_id:
            statement = statement.where(KnowledgeIngestionJob.document_id == str(document_id))
        rows = (await session.scalars(statement.order_by(
            KnowledgeIngestionJob.created_at.desc()
        ).limit(limit).offset(offset))).all()
        return [JobResponse.model_validate(row) for row in rows]


@router.post("/knowledge-documents/{document_id}/versions/{version_id}/ingest",
             response_model=JobResponse, status_code=202)
async def ingest(document_id: UUID, version_id: UUID, payload: IngestionRequest, request: Request):
    try:
        async with factory(request).begin() as session:
            version = await session.get(KnowledgeDocumentVersion, str(version_id))
            document = await session.get(KnowledgeDocument, str(document_id))
            profile = await session.get(KnowledgeEmbeddingProfile, str(payload.profile_id))
            if (
                version is None or document is None or profile is None
                or version.document_id != document.id
            ):
                raise HTTPException(404, detail="文档、版本或 Profile 不存在")
            if document.status != "active":
                raise HTTPException(409, detail="请先恢复已归档文档")
            current = await session.scalar(select(KnowledgeIngestionJob).where(
                KnowledgeIngestionJob.active_key == document.id
            ))
            if current:
                raise HTTPException(409, detail="当前文档已有处理中任务")
            job = KnowledgeIngestionJob(
                document_id=document.id, version_id=version.id,
                profile_id=profile.id, active_key=document.id,
                chunk_size=payload.chunk_size, chunk_overlap=payload.chunk_overlap,
                rebuild=payload.rebuild,
            )
            session.add(job)
            await session.flush()
            response = JobResponse.model_validate(job)
    except IntegrityError as error:
        raise HTTPException(409, detail="当前文档已有处理中任务") from error
    request.app.state.knowledge_job_manager.start(response.id)
    return response


@router.post("/knowledge/jobs/{job_id}/cancel", status_code=202)
async def cancel(job_id: UUID, request: Request):
    async with factory(request)() as session:
        if await session.get(KnowledgeIngestionJob, str(job_id)) is None:
            raise HTTPException(404, detail="Job not found")
    await request.app.state.knowledge_job_manager.cancel(str(job_id))
    return {"id": str(job_id), "cancel_requested": True}
