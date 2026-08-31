"""Application settings loaded from environment variables and .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration.

    Every environment variable uses the PAWTEAM_ prefix. Paths remain
    configurable so tests and Docker never need to write into the source tree.
    """

    model_config = SettingsConfigDict(
        env_prefix="PAWTEAM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PawTeam Lite"
    version: str = "0.1.0"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    data_dir: Path = Path("data")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
