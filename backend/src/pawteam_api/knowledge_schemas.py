"""Validation contracts for managed knowledge bases."""

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing import Literal
from uuid import UUID

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


class KnowledgeDocumentParseResultResponse(BaseModel):
    """返回解析后的文本及其处理规则，不暴露文件存储位置。"""

    version_id: str
    text: str
    char_count: int
    source_format: str
    parser_name: str
    parser_version: str
    created_at: datetime


class KnowledgeChunkingConfig(BaseModel):
    """一组可复现的切块参数，长度单位是 Unicode 字符。"""

    model_config = ConfigDict(extra="forbid")

    # 设置默认值，后续 API 可不带参数直接使用这组基准配置。
    # 最大值用于限制单块大小，不能替代 embedding 模型的 Token 限制。
    chunk_size: int = Field(default=800, ge=1, le=10_000)

    # 重叠减少边界处上下文断裂，但会增加存储和后续向量化成本。
    chunk_overlap: int = Field(default=100, ge=0, le=9_999)

    @model_validator(mode="after")
    def overlap_must_be_smaller_than_chunk(self) -> "KnowledgeChunkingConfig":
        # 数据库也有同样约束；这里提前给调用方清楚的参数校验错误。
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size")
        return self


class KnowledgeChunkResponse(BaseModel):
    """返回一个片段及其在解析文本中的字符位置。"""

    id: str
    chunk_index: int
    text: str
    char_count: int
    start_char: int
    end_char: int


class KnowledgeChunkSetResponse(BaseModel):
    """返回一次切块批次的参数和全部片段。"""

    id: str
    version_id: str
    source_text_sha256: str
    splitter_name: str
    splitter_version: str
    chunk_size: int
    chunk_overlap: int
    created_at: datetime
    chunks: list[KnowledgeChunkResponse]


class KnowledgeChunkSetSummary(BaseModel):
    """批次元信息，用于列表和详情查询，不包含片段正文。"""

    # 允许从 SQLAlchemy 对象的同名属性读取字段。
    # 在数据库会话关闭前，将 ORM 对象转换为独立的响应对象。
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_id: str
    source_text_sha256: str
    splitter_name: str
    splitter_version: str
    chunk_size: int
    chunk_overlap: int
    created_at: datetime


class KnowledgeChunkPage(BaseModel):
    """一个切块批次中的片段分页结果。"""

    chunk_set_id: str

    # total 是整个批次的片段数，不是当前页的片段数。
    total: int
    limit: int
    offset: int

    # 复用已有的片段响应模型，保持字符偏移字段定义一致。
    items: list[KnowledgeChunkResponse]


class KnowledgeVectorIndexResponse(BaseModel):
    """索引任务的数据库状态，不包含向量和文档正文。"""

    # 在 Session 关闭前，把 ORM 对象转换为独立响应。
    model_config = ConfigDict(from_attributes=True)

    profile_id: str
    chunk_set_id: str
    status: Literal["pending", "indexing", "indexed", "failed"]

    expected_points: int
    indexed_points: int
    attempts: int

    last_error: str | None
    lease_until: datetime | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeVectorIndexExecutionResponse(BaseModel):
    """执行摘要；reused 表示本次复用了已完成状态。"""

    model_config = ConfigDict(from_attributes=True)

    profile_id: str
    chunk_set_id: str
    point_count: int
    reused: bool


class KnowledgeEmbeddingProfileCreate(BaseModel):
    """创建一份向量配置，不接收密钥或客户端指定的服务地址。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    # 从已有 Provider 及其模型中选择，避免手写模型名称产生拼写错误。
    provider_id: UUID
    model_id: UUID

    # 平台维护的配置版本标签，不代表上游已经固定模型权重。
    model_revision: str = Field(
        default="1",
        min_length=1,
        max_length=100,
    )

    # 这里是平台的输入保护范围，不代表具体模型支持这些维度。
    # strict=True 拒绝字符串数字及布尔值。
    dimensions: int = Field(strict=True, ge=1, le=65_536)

    # 只有确认模型支持 dimensions 参数时才启用。
    send_dimensions: bool = Field(default=False, strict=True)

    # 当前向量化服务只支持直接使用原始片段正文。
    input_policy_version: Literal["raw-v1"] = "raw-v1"


class KnowledgeEmbeddingProfileResponse(BaseModel):
    """返回配置快照，不返回 Provider 密钥及其存储引用。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    base_url: str
    model_name: str
    model_revision: str
    dimensions: int
    send_dimensions: bool
    input_policy_version: str
    created_at: datetime


class KnowledgeEmbeddingExecutionResponse(BaseModel):
    """返回向量化执行摘要，不返回体积较大的向量数组。"""

    # Service 返回的是数据类。
    # 开启此配置后，Pydantic 可以直接读取数据类的同名属性。
    model_config = ConfigDict(from_attributes=True)

    chunk_set_id: str
    profile_id: str

    # 本次批次包含的片段数量，不是模型请求次数。
    chunk_count: int

    # True 表示数据库已有完整有效的结果，本次直接复用。
    reused: bool