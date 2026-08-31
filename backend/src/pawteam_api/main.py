"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pawteam_api.api.router import api_router
from pawteam_api.config import Settings, get_settings
from pawteam_api.database import create_database_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings.ensure_directories()
        app.state.settings = resolved_settings
        app.state.db_engine = create_database_engine(resolved_settings)
        yield
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
