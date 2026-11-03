import pytest
from pydantic import ValidationError

from pawteam_api.knowledge.embeddings import EmbeddingBatch


def test_accepts_valid_vectors() -> None:
    # 保留原始数值和顺序，不能在校验时悄悄改变模型输出。
    vectors = [[1.0, 2.0], [-1.0, 3.0]]
    assert EmbeddingBatch(dimensions=2, vectors=vectors).vectors == vectors


@pytest.mark.parametrize("vectors", [
    [], [[1.0]], [[0.0, 0.0]],
    [[float("nan"), 1.0]], [[float("inf"), 1.0]],
    [[True, 1.0]], [["1.0", 1.0]],
])
def test_rejects_invalid_vectors(vectors) -> None:
    # 覆盖空批次、维度错误、零向量、非法数值及错误类型。
    with pytest.raises(ValidationError):
        EmbeddingBatch(dimensions=2, vectors=vectors)