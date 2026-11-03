import pytest
from pydantic import ValidationError

from pawteam_api.knowledge.chunking import (
    KnowledgeTextChunker,
    KnowledgeChunkingInputError,
    KnowledgeChunkingLimitError,
)
from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig


def test_config_uses_defaults() -> None:
    config = KnowledgeChunkingConfig()

    assert config.chunk_size == 800
    assert config.chunk_overlap == 100


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [
        (0, 0),
        (10_001, 0),
        (10, -1),
        (10, 10),
        (10, 11),
    ],
)
def test_config_rejects_invalid_values(
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    with pytest.raises(ValidationError):
        KnowledgeChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def test_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeChunkingConfig(
            chunk_size=100,
            chunk_overlap=10,
            storage_key="not-a-chunk-option",
        )


def test_long_text_uses_hard_boundaries_and_exact_overlap() -> None:
    text = "abcdefghijklmnopqrst"
    config = KnowledgeChunkingConfig(chunk_size=8, chunk_overlap=2)

    chunks = KnowledgeTextChunker(config).split(text)

    assert [(item.start_char, item.end_char) for item in chunks] == [
        (0, 8),
        (6, 14),
        (12, 20),
    ]
    assert [item.text for item in chunks] == [
        "abcdefgh",
        "ghijklmn",
        "mnopqrst",
    ]


def test_chunker_prefers_paragraph_boundary_over_later_newline() -> None:
    text = "abcdefgh\n\nij\nklmnop"
    config = KnowledgeChunkingConfig(chunk_size=15, chunk_overlap=2)

    chunks = KnowledgeTextChunker(config).split(text)

    # 虽然普通换行更靠近硬边界，段落边界优先级更高。
    assert chunks[0].end_char == text.index("\n\n") + 2
    assert chunks[0].text.endswith("\n\n")


def test_chunk_offsets_reconstruct_each_slice_for_unicode() -> None:
    text = "中文和🙂符号\n下一段包含更多文本"
    config = KnowledgeChunkingConfig(chunk_size=8, chunk_overlap=2)

    chunks = KnowledgeTextChunker(config).split(text)

    for expected_index, chunk in enumerate(chunks):
        assert chunk.chunk_index == expected_index
        assert chunk.text == text[chunk.start_char:chunk.end_char]
        assert chunk.char_count == chunk.end_char - chunk.start_char
        assert chunk.char_count <= config.chunk_size

    # 所有原文位置都必须被覆盖；块之间允许重叠，但不能留空洞。
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert following.start_char <= previous.end_char


def test_small_input_produces_one_unchanged_chunk() -> None:
    text = "# 标题\n正文"
    chunks = KnowledgeTextChunker(
        KnowledgeChunkingConfig(chunk_size=100, chunk_overlap=10)
    ).split(text)

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == len(text)


@pytest.mark.parametrize("text", ["", " \t\n"])
def test_chunker_rejects_empty_or_blank_text(text: str) -> None:
    chunker = KnowledgeTextChunker(KnowledgeChunkingConfig())

    with pytest.raises(KnowledgeChunkingInputError):
        chunker.split(text)


def test_chunker_rejects_input_that_exceeds_chunk_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超过服务端片段上限时，应停止处理而不是继续分配对象。"""

    # 测试中将上限缩小到 2，避免创建 5,000 个片段来验证边界。
    # 生产环境仍使用 KnowledgeTextChunker.max_chunks 的默认值。
    monkeypatch.setattr(KnowledgeTextChunker, "max_chunks", 2)

    chunker = KnowledgeTextChunker(
        KnowledgeChunkingConfig(chunk_size=1, chunk_overlap=0)
    )

    # chunk_size=1、overlap=0 时，每个字符都会生成一个片段。
    with pytest.raises(KnowledgeChunkingLimitError):
        chunker.split("abc")