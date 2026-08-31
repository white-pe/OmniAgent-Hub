"""Top-level API router."""

from fastapi import APIRouter

from pawteam_api.api.routes.agents import router as agents_router
from pawteam_api.api.routes.auth import router as auth_router
from pawteam_api.api.routes.blueprints import router as blueprints_router
from pawteam_api.api.routes.channels import router as channels_router
from pawteam_api.api.routes.chats import router as chats_router
from pawteam_api.api.routes.health import router as health_router
from pawteam_api.api.routes.providers import router as providers_router
from pawteam_api.api.routes.runs import router as runs_router
from pawteam_api.api.routes.skills import router as skills_router
from pawteam_api.api.routes.teams import router as teams_router
from pawteam_api.api.routes.tools import router as tools_router
from pawteam_api.api.routes.wecom_webhooks import router as wecom_webhooks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(providers_router)
api_router.include_router(blueprints_router)
api_router.include_router(agents_router)
api_router.include_router(chats_router)
api_router.include_router(channels_router)
api_router.include_router(runs_router)
api_router.include_router(skills_router)
api_router.include_router(tools_router)
api_router.include_router(teams_router)
api_router.include_router(wecom_webhooks_router)
