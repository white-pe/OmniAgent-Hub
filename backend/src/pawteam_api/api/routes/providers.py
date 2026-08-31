"""Provider CRUD, connection testing, and streaming completion endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.provider_schemas import (
    ProviderChatRequest,
    ProviderCreate,
    ProviderResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderUpdate,
)
from pawteam_api.providers.client import ProviderRequestError
from pawteam_api.providers.service import (
    ProviderConflictError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
    ProviderService,
)
from pawteam_api.security.secret_store import SecretNotFoundError

router = APIRouter(prefix="/providers", tags=["providers"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def provider_service(request: Request, session: AsyncSession) -> ProviderService:
    return ProviderService(session, request.app.state.secret_store)


def translate_service_error(error: Exception) -> HTTPException:
    if isinstance(error, ProviderNotFoundError):
        return HTTPException(status_code=404, detail="Provider not found")
    if isinstance(error, ProviderModelNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, SecretNotFoundError):
        return HTTPException(
            status_code=409, detail="Provider API key is not configured"
        )
    if isinstance(error, ProviderConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Provider error")


@router.get("", response_model=list[ProviderResponse])
async def list_providers(
    request: Request,
    session: SessionDependency,
) -> list[ProviderResponse]:
    return await provider_service(request, session).list()


@router.post("", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    request: Request,
    session: SessionDependency,
) -> ProviderResponse:
    try:
        return await provider_service(request, session).create(payload)
    except (ProviderConflictError, ValueError) as error:
        raise translate_service_error(error) from error


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    request: Request,
    session: SessionDependency,
) -> ProviderResponse:
    try:
        return await provider_service(request, session).get(provider_id)
    except ProviderNotFoundError as error:
        raise translate_service_error(error) from error


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    request: Request,
    session: SessionDependency,
) -> ProviderResponse:
    try:
        return await provider_service(request, session).update(provider_id, payload)
    except (ProviderNotFoundError, ProviderConflictError, ValueError) as error:
        raise translate_service_error(error) from error


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: str,
    request: Request,
    session: SessionDependency,
) -> Response:
    try:
        await provider_service(request, session).delete(provider_id)
    except ProviderNotFoundError as error:
        raise translate_service_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/test", response_model=ProviderTestResponse)
async def test_provider(
    provider_id: str,
    payload: ProviderTestRequest,
    request: Request,
    session: SessionDependency,
) -> ProviderTestResponse:
    try:
        runtime = await provider_service(request, session).runtime(
            provider_id, payload.model_id
        )
    except (
        ProviderNotFoundError,
        ProviderModelNotFoundError,
        ProviderConflictError,
        SecretNotFoundError,
    ) as error:
        raise translate_service_error(error) from error

    client = request.app.state.provider_client_factory(
        runtime.base_url,
        runtime.api_key,
        request.app.state.settings.provider_timeout_seconds,
    )
    started_at = perf_counter()
    try:
        reply = await client.test(runtime.model_name)
    except ProviderRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return ProviderTestResponse(
        ok=True,
        model=runtime.model_name,
        latency_ms=round((perf_counter() - started_at) * 1000),
        reply_preview=reply[:200],
    )


@router.post("/{provider_id}/chat/stream")
async def stream_provider_chat(
    provider_id: str,
    payload: ProviderChatRequest,
    request: Request,
    session: SessionDependency,
) -> StreamingResponse:
    try:
        runtime = await provider_service(request, session).runtime(
            provider_id, payload.model_id
        )
    except (
        ProviderNotFoundError,
        ProviderModelNotFoundError,
        ProviderConflictError,
        SecretNotFoundError,
    ) as error:
        raise translate_service_error(error) from error

    client = request.app.state.provider_client_factory(
        runtime.base_url,
        runtime.api_key,
        request.app.state.settings.provider_timeout_seconds,
    )

    async def events() -> AsyncIterator[str]:
        yield encode_sse(
            "start",
            {
                "provider_id": runtime.provider_id,
                "model_id": runtime.model_id,
                "model": runtime.model_name,
            },
        )
        try:
            async for content in client.stream(
                model=runtime.model_name,
                prompt=payload.prompt,
                system_prompt=payload.system_prompt,
                temperature=payload.temperature,
            ):
                yield encode_sse("delta", {"content": content})
        except ProviderRequestError as error:
            yield encode_sse("error", {"message": str(error)})
            return
        yield encode_sse("done", {"model": runtime.model_name})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def encode_sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
