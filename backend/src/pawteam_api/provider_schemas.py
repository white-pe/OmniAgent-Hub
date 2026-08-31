"""Validation contracts for Provider management and model testing."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class ProviderModelInput(BaseModel):
    model_name: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    capabilities: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Model name cannot be empty")
        return normalized

    @model_validator(mode="after")
    def fill_display_name(self) -> "ProviderModelInput":
        if self.display_name is None or not self.display_name.strip():
            self.display_name = self.model_name
        else:
            self.display_name = self.display_name.strip()
        return self


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr
    enabled: bool = True
    models: list[ProviderModelInput] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Provider name cannot be empty")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("Base URL must not contain credentials")
        return normalized

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API key cannot be empty")
        return SecretStr(value.get_secret_value().strip())

    @model_validator(mode="after")
    def reject_duplicate_models(self) -> "ProviderCreate":
        names = [model.model_name for model in self.models]
        if len(names) != len(set(names)):
            raise ValueError("Model names must be unique within a Provider")
        return self


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: SecretStr | None = None
    enabled: bool | None = None
    models: list[ProviderModelInput] | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Provider name cannot be empty")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_optional_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ProviderCreate.validate_base_url(value)

    @field_validator("api_key")
    @classmethod
    def validate_optional_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        return ProviderCreate.validate_api_key(value)

    @model_validator(mode="after")
    def validate_models(self) -> "ProviderUpdate":
        if self.models is not None:
            if not self.models:
                raise ValueError("A Provider must expose at least one model")
            names = [model.model_name for model in self.models]
            if len(names) != len(set(names)):
                raise ValueError("Model names must be unique within a Provider")
        return self


class ProviderModelResponse(BaseModel):
    id: str
    model_name: str
    display_name: str
    capabilities: dict[str, object]
    enabled: bool


class ProviderResponse(BaseModel):
    id: str
    name: str
    kind: str
    base_url: str
    enabled: bool
    configured: bool
    created_at: datetime
    updated_at: datetime
    models: list[ProviderModelResponse]


class ProviderTestRequest(BaseModel):
    model_id: str | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    model: str
    latency_ms: int
    reply_preview: str


class ProviderChatRequest(BaseModel):
    model_id: str
    prompt: str = Field(min_length=1, max_length=20_000)
    system_prompt: str | None = Field(default=None, max_length=10_000)
    temperature: float = Field(default=0.7, ge=0, le=2)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Prompt cannot be empty")
        return normalized
