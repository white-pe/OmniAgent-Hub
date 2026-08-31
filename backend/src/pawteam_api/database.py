"""Database engine construction and health checks."""

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pawteam_api.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.environment == "development",
        pool_pre_ping=True,
    )
    if settings.database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))
        return result.scalar_one() == 1
