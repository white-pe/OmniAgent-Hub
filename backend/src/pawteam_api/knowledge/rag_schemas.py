"""管理台、后台任务及检索共享的显式数据契约。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=4000)
    # Agent 模式下由后端绑定计算范围；不能传入知识库列表覆盖授权。
    agent_id: UUID | None = None
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=20)
    profile_id: UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20, strict=True)
    min_score: float = Field(default=0.0, ge=-1, le=1)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.agent_id is not None and self.knowledge_base_ids:
            raise ValueError("Agent scope cannot be overridden")
        if self.agent_id is None and not self.knowledge_base_ids:
            raise ValueError("Select knowledge bases or an Agent")
        return self


class RetrievalHit(BaseModel):
    citation: str
    chunk_id: str
    chunk_set_id: str
    profile_id: str
    knowledge_base_id: str
    document_id: str
    version_id: str
    title: str
    filename: str
    version_number: int
    chunk_index: int
    start_char: int
    end_char: int
    score: float
    text: str


class RetrievalResponse(BaseModel):
    request_id: str
    hits: list[RetrievalHit]
    latency_ms: int
    searched_profiles: list[str]


class AnswerRequest(RetrievalRequest):
    # 普通管理台问答选择聊天模型；Agent 模式使用 Agent 自身的模型。
    provider_id: UUID | None = None
    model_id: UUID | None = None

    @model_validator(mode="after")
    def validate_model(self):
        if self.agent_id is None and (
            self.provider_id is None or self.model_id is None
        ):
            raise ValueError("Select a generation provider and model")
        if self.agent_id is not None and (
            self.provider_id is not None or self.model_id is not None
        ):
            raise ValueError("Agent generation model cannot be overridden")
        return self


class AnswerResponse(RetrievalResponse):
    answer: str
    status: Literal["answered", "insufficient_evidence", "invalid_citations"]
    cited_ids: list[str]


class IngestionRequest(KnowledgeChunkingConfig):
    profile_id: UUID
    rebuild: bool = False


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: str
    version_id: str
    profile_id: str
    status: str
    stage: str
    chunk_size: int
    chunk_overlap: int
    chunk_set_id: str | None
    rebuild: bool
    cancel_requested: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class PublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_set_id: UUID
    profile_id: UUID


class PublicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: str
    chunk_set_id: str
    profile_id: str
    updated_at: datetime
