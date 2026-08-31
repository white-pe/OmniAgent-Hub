"""Run status, cancellation, and replayable Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.chat_schemas import RunResponse
from pawteam_api.models import AgentRun, RunEvent
from pawteam_api.runtime.service import (
    TERMINAL_RUN_STATUSES,
    RunCommandService,
    RunNotFoundError,
)

router = APIRouter(prefix="/runs", tags=["runs"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def translate_run_error(error: Exception) -> HTTPException:
    if isinstance(error, RunNotFoundError):
        return HTTPException(status_code=404, detail="Run not found")
    return HTTPException(status_code=500, detail="Unexpected Run error")


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, session: SessionDependency) -> RunResponse:
    try:
        return await RunCommandService(session).get(run_id)
    except RunNotFoundError as error:
        raise translate_run_error(error) from error


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: str,
    request: Request,
    session: SessionDependency,
) -> RunResponse:
    try:
        await RunCommandService(session).request_cancel(run_id)
    except RunNotFoundError as error:
        raise translate_run_error(error) from error
    await request.app.state.run_manager.cancel(run_id)
    session.expire_all()
    return await RunCommandService(session).get(run_id)


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    async with request.app.state.session_factory() as lookup_session:
        if await lookup_session.get(AgentRun, run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
    cursor = max(after, _event_id(last_event_id))

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        heartbeat_at = asyncio.get_running_loop().time()
        while True:
            if await request.is_disconnected():
                return
            async with request.app.state.session_factory() as event_session:
                rows = (
                    await event_session.scalars(
                        select(RunEvent)
                        .where(
                            RunEvent.run_id == run_id,
                            RunEvent.sequence > cursor,
                        )
                        .order_by(RunEvent.sequence)
                    )
                ).all()
                run_status = await event_session.scalar(
                    select(AgentRun.status).where(AgentRun.id == run_id)
                )
            for event in rows:
                cursor = event.sequence
                yield encode_sse(event.sequence, event.event_type, event.data_json)
            if run_status in TERMINAL_RUN_STATUSES:
                return
            now = asyncio.get_running_loop().time()
            if now - heartbeat_at >= 15:
                heartbeat_at = now
                yield encode_sse(None, "heartbeat", {"run_id": run_id})
            await asyncio.sleep(
                request.app.state.settings.run_event_poll_interval_seconds
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def encode_sse(sequence: int | None, event: str, data: dict[str, object]) -> str:
    event_id = f"id: {sequence}\n" if sequence is not None else ""
    payload = json.dumps(data, ensure_ascii=False)
    return f"{event_id}event: {event}\ndata: {payload}\n\n"


def _event_id(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0
