"""Application settings loaded from environment variables and .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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

    app_name: str = "OmniAgent"
    version: str = "1.0.0"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    data_dir: Path = Path("data")
    secrets_dir: Path = Path("data/secrets")
    workspaces_dir: Path = Path("data/workspaces")
    secret_key: SecretStr | None = None
    admin_password: SecretStr | None = None
    auth_secret_key: SecretStr | None = None
    auth_session_hours: int = 12
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    provider_timeout_seconds: float = 60.0
    blueprint_ttl_minutes: int = 1440
    run_timeout_seconds: float = 120.0
    run_event_poll_interval_seconds: float = 0.15
    runtime_history_messages: int = 30
    runtime_history_chars: int = 40_000
    runtime_workspace_file_chars: int = 15_000
    runtime_skill_chars: int = 10_000
    runtime_max_steps: int = 8
    tool_timeout_seconds: float = 10.0
    tool_result_max_chars: int = 20_000
    tool_event_preview_chars: int = 1_000
    delegation_max_depth: int = 2
    delegation_max_calls_per_root: int = 6
    delegation_task_max_chars: int = 8_000
    channel_signature_tolerance_seconds: int = 300
    channel_outbox_lease_seconds: int = 30
    channel_outbox_max_attempts: int = 5
    channel_outbox_batch_size: int = 20
    channel_delivery_timeout_seconds: float = 10.0
    channel_qr_session_seconds: int = 300
    channel_wecom_reconnect_attempts: int = -1
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    knowledge_max_upload_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1,
        le=1024 * 1024 * 1024,
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() == "production"

    @property
    def auth_enabled(self) -> bool:
        return self.admin_password is not None

    def validate_runtime(self) -> None:
        """Fail closed when a production deployment omitted a security secret."""
        if not self.is_production:
            return

        missing: list[str] = []
        if self.admin_password is None or len(
            self.admin_password.get_secret_value()
        ) < 12:
            missing.append("PAWTEAM_ADMIN_PASSWORD (at least 12 characters)")
        if self.auth_secret_key is None or len(
            self.auth_secret_key.get_secret_value()
        ) < 32:
            missing.append("PAWTEAM_AUTH_SECRET_KEY (at least 32 characters)")
        if self.secret_key is None:
            missing.append("PAWTEAM_SECRET_KEY (a Fernet key)")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            missing.append("PAWTEAM_ALLOWED_HOSTS (must not contain '*')")
        if missing:
            raise RuntimeError(
                "Unsafe production configuration: " + "; ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
