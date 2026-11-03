"""Validated embedding data shared by clients and indexing services."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class EmbeddingBatch(BaseModel):
    """一批按输入文本顺序排列、维度相同的向量。"""

    # 拒绝未知字段和字符串数值、布尔值等隐式类型转换。
    model_config = ConfigDict(strict=True, extra="forbid")

    # 由调用方根据模型配置传入，不能根据错误响应随意推断。
    dimensions: int = Field(ge=1)

    # FiniteFloat 拒绝 NaN、正负无穷，避免污染后续索引和评分。
    vectors: list[list[FiniteFloat]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_vectors(self) -> Self:
        for vector in self.vectors:
            # 同一批次的向量必须符合预期维度。
            if len(vector) != self.dimensions:
                raise ValueError("Embedding dimension mismatch")
            # 本项目准备使用余弦相似度，拒绝无法计算该相似度的零向量。
            if not any(value != 0 for value in vector):
                raise ValueError("Embedding vector must not be zero")
        return self