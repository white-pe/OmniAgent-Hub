"""Service and database readiness endpoint."""

from fastapi import APIRouter, Request, Response, status

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


@router.get("/health/live", status_code=204)
async def liveness() -> None:
    """The process can accept HTTP requests; no dependency check is performed."""


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(request: Request, response: Response) -> HealthResponse:
    result = await health(request)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
