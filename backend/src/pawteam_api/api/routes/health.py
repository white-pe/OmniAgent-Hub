"""Service and database readiness endpoint."""

from fastapi import APIRouter, Request

from pawteam_api.database import check_database
from pawteam_api.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings

    try:
        database_ok = await check_database(request.app.state.db_engine)
    except Exception:
        database_ok = False

    return HealthResponse(
        name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "unavailable",
    )
