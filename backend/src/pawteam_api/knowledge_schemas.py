"""Validation contracts for managed knowledge bases."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)

    @field_validator("name", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Knowledge base name cannot be empty")
        return value


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    enabled: bool | None = None

    @field_validator("name", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("name")
    @classmethod
    def optional_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("Knowledge base name cannot be empty")
        return value


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: str = Field(min_length=1, max_length=36)


class KnowledgeBaseBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class KnowledgeBaseBindingResponse(BaseModel):
    agent_id: str
    knowledge_base_id: str
    knowledge_base_name: str
    enabled: bool
    created_at: datetime


class KnowledgeDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Document title cannot be empty")
        return value


class KnowledgeDocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    version_number: int
    original_filename: str
    media_type: str | None
    size_bytes: int
    sha256: str
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime