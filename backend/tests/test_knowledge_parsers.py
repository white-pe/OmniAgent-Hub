import codecs

import pytest

from pawteam_api.knowledge.parsers import (
    KnowledgeTextContentError,
    KnowledgeTextEncodingError,
    KnowledgeTextParser,
    KnowledgeTextTooLargeError,
    UnsupportedKnowledgeTextFormatError,
)


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    [
        ("guide.txt", "txt"),
        ("guide.MD", "markdown"),
        ("guide.markdown", "markdown"),
    ],
)
def test_parser_accepts_supported_formats(
    filename: str,
    expected_format: str,
) -> None:
    """支持的后缀能够正确路由，并保留中文内容。"""

    parser = KnowledgeTextParser()
    text = "中文知识库\nAPI Guide"

    result = parser.parse(text.encode("utf-8"), filename)

    assert result.text == text
    assert result.source_format == expected_format
    assert result.parser_name == "utf8-text"
    assert result.parser_version == "1"


def test_parser_removes_initial_bom_and_normalizes_newlines() -> None:
    """混合换行规范化后，不能额外产生空行。"""

    parser = KnowledgeTextParser()
    content = codecs.BOM_UTF8 + b"first\r\nsecond\rthird\n"

    result = parser.parse(content, "guide.txt")

    assert result.text == "first\nsecond\nthird\n"


def test_parser_preserves_markdown_whitespace() -> None:
    """保留代码缩进、尾随空格及首尾空行。"""

    parser = KnowledgeTextParser()
    text = (
        "\n# Guide\n\n"
        "```python\n"
        "    print('hello')\n"
        "```\n"
        "line with spaces  \n\n"
    )

    result = parser.parse(text.encode("utf-8"), "guide.md")

    assert result.text == text


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b" \t\r\n",
        codecs.BOM_UTF8,
    ],
)
def test_parser_rejects_blank_text(content: bytes) -> None:
    """空字节、只有空白、只有 BOM，都不能成为有效解析结果。"""

    with pytest.raises(KnowledgeTextContentError):
        KnowledgeTextParser().parse(content, "guide.txt")


@pytest.mark.parametrize(
    "content",
    [
        b"\xff",
        "中文".encode("utf-16"),
    ],
)
def test_parser_rejects_invalid_utf8(content: bytes) -> None:
    """非法 UTF-8 或不支持的编码应明确失败。"""

    with pytest.raises(KnowledgeTextEncodingError):
        KnowledgeTextParser().parse(content, "guide.txt")


def test_parser_rejects_nul_characters() -> None:
    """可成功解码的内容，仍然需要通过文本内容校验。"""

    with pytest.raises(KnowledgeTextContentError, match="NUL"):
        KnowledgeTextParser().parse(b"hello\x00world", "guide.txt")


@pytest.mark.parametrize("filename", ["guide.pdf", "guide"])
def test_parser_rejects_unsupported_formats(filename: str) -> None:
    """不能因为字节恰好能解码，就接受不支持的文件格式。"""

    with pytest.raises(UnsupportedKnowledgeTextFormatError):
        KnowledgeTextParser().parse(b"content", filename)


def test_parser_enforces_character_limit() -> None:
    """限制的是字符数量，而不是 UTF-8 字节数量。"""

    parser = KnowledgeTextParser(max_text_chars=3)

    # 三个中文字符的 UTF-8 字节数大于 3，但字符数符合约束。
    result = parser.parse("知识库".encode("utf-8"), "guide.txt")
    assert result.text == "知识库"

    # 恰好达到限制可以通过，超过一个字符则拒绝。
    with pytest.raises(KnowledgeTextTooLargeError):
        parser.parse("知识库文".encode("utf-8"), "guide.txt")


@pytest.mark.parametrize("max_text_chars", [0, -1])
def test_parser_rejects_invalid_configuration(max_text_chars: int) -> None:
    """非法配置在初始化阶段就失败。"""

    with pytest.raises(ValueError, match="positive"):
        KnowledgeTextParser(max_text_chars=max_text_chars)