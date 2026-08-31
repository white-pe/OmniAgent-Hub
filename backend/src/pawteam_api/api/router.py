"""Top-level API router."""

from fastapi import APIRouter

from pawteam_api.api.routes.agents import router as agents_router
from pawteam_api.api.routes.health import router as health_router
from pawteam_api.api.routes.providers import router as providers_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(providers_router)
api_router.include_router(agents_router)
