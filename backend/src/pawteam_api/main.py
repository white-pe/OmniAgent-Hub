"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pawteam_api.api.router import api_router
from pawteam_api.config import Settings, get_settings
from pawteam_api.database import create_database_engine, create_session_factory
from pawteam_api.providers.client import OpenAICompatibleClient
from pawteam_api.runtime.manager import RunManager
from pawteam_api.security.secret_store import SecretStore
from pawteam_api.tools.registry import ToolRegistry
from pawteam_api.workspaces.store import WorkspaceStore


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings.ensure_directories()
        app.state.settings = resolved_settings
        app.state.db_engine = create_database_engine(resolved_settings)
        app.state.session_factory = create_session_factory(app.state.db_engine)
        app.state.secret_store = SecretStore(resolved_settings)
        app.state.workspace_store = WorkspaceStore(resolved_settings)
        app.state.tool_registry = ToolRegistry(
            resolved_settings, app.state.workspace_store
        )
        app.state.provider_client_factory = OpenAICompatibleClient
        app.state.run_manager = RunManager(
            session_factory=app.state.session_factory,
            settings=resolved_settings,
            secret_store=app.state.secret_store,
            workspace_store=app.state.workspace_store,
            tool_registry=app.state.tool_registry,
            provider_client_factory=lambda base_url, api_key, timeout: (
                app.state.provider_client_factory(base_url, api_key, timeout)
            ),
        )
        await app.state.run_manager.recover_interrupted_runs()
        yield
        await app.state.run_manager.shutdown()
        await app.state.db_engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_app()
