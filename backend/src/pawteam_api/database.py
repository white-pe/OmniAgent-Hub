"""Database engine construction and health checks."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from pawteam_api.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.environment == "development",
        pool_pre_ping=True,
    )


async def check_database(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))
        return result.scalar_one() == 1
