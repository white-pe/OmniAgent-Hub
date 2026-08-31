"""Generate, inspect, and cancel reviewable Agent Blueprint drafts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.api.dependencies import get_database_session
from pawteam_api.blueprint_schemas import (
    BlueprintDraftResponse,
    BlueprintGenerateRequest,
)
from pawteam_api.blueprints.service import (
    BlueprintConflictError,
    BlueprintGenerationError,
    BlueprintNotFoundError,
    BlueprintService,
)
from pawteam_api.providers.client import ProviderRequestError
from pawteam_api.providers.service import (
    ProviderConflictError,
    ProviderModelNotFoundError,
    ProviderNotFoundError,
)
from pawteam_api.security.secret_store import SecretNotFoundError

router = APIRouter(prefix="/agent-blueprints", tags=["agent-blueprints"])
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


def blueprint_service(request: Request, session: AsyncSession) -> BlueprintService:
    return BlueprintService(
        session=session,
        settings=request.app.state.settings,
        secret_store=request.app.state.secret_store,
        workspace_store=request.app.state.workspace_store,
        provider_client_factory=request.app.state.provider_client_factory,
    )


def translate_blueprint_error(error: Exception) -> HTTPException:
    if isinstance(error, BlueprintNotFoundError):
        return HTTPException(status_code=404, detail="Blueprint draft not found")
    if isinstance(error, (BlueprintConflictError, ProviderConflictError)):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ProviderModelNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ProviderNotFoundError):
        return HTTPException(status_code=404, detail="Provider not found")
    if isinstance(error, SecretNotFoundError):
        return HTTPException(
            status_code=409, detail="Provider API key is not configured"
        )
    if isinstance(error, (ProviderRequestError, BlueprintGenerationError)):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected Blueprint error")


@router.post(
    "/generate",
    response_model=BlueprintDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_blueprint(
    payload: BlueprintGenerateRequest,
    request: Request,
    session: SessionDependency,
) -> BlueprintDraftResponse:
    try:
        return await blueprint_service(request, session).generate(payload)
    except (
        ProviderNotFoundError,
        ProviderModelNotFoundError,
        ProviderConflictError,
        SecretNotFoundError,
        ProviderRequestError,
        BlueprintGenerationError,
    ) as error:
        raise translate_blueprint_error(error) from error


@router.get("/{draft_id}", response_model=BlueprintDraftResponse)
async def get_blueprint(
    draft_id: str,
    request: Request,
    session: SessionDependency,
) -> BlueprintDraftResponse:
    try:
        return await blueprint_service(request, session).get(draft_id)
    except (BlueprintNotFoundError, BlueprintGenerationError) as error:
        raise translate_blueprint_error(error) from error


@router.post("/{draft_id}/cancel", response_model=BlueprintDraftResponse)
async def cancel_blueprint(
    draft_id: str,
    request: Request,
    session: SessionDependency,
) -> BlueprintDraftResponse:
    try:
        return await blueprint_service(request, session).cancel(draft_id)
    except (
        BlueprintNotFoundError,
        BlueprintConflictError,
        BlueprintGenerationError,
    ) as error:
        raise translate_blueprint_error(error) from error
