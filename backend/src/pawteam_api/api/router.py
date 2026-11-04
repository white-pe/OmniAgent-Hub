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
from pawteam_api.api.routes.knowledge import (
    agent_binding_router,
    router as knowledge_router,
)
from pawteam_api.api.routes.knowledge_documents import (
    router as knowledge_documents_router,
)
from pawteam_api.api.routes.knowledge_chunks import (
    router as knowledge_chunks_router,
)
from pawteam_api.api.routes.knowledge_indexes import (
    router as knowledge_indexes_router,
)

from pawteam_api.api.routes.knowledge_embedding_profiles import (
    router as knowledge_embedding_profiles_router,
)
from pawteam_api.api.routes.knowledge_embeddings import (
    router as knowledge_embeddings_router,
)

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
api_router.include_router(knowledge_router)
api_router.include_router(agent_binding_router)
api_router.include_router(knowledge_documents_router)
api_router.include_router(knowledge_chunks_router)
api_router.include_router(knowledge_indexes_router)
api_router.include_router(knowledge_embedding_profiles_router)
api_router.include_router(knowledge_embeddings_router)