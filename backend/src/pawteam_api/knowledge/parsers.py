"""Deterministic UTF-8 text extraction for TXT and Markdown sources."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal


class KnowledgeTextParseError(ValueError):
    """文本解析业务异常的共同基类，方便后续任务统一捕获。"""


class UnsupportedKnowledgeTextFormatError(KnowledgeTextParseError):
    """当前解析器不支持该文件后缀。"""


class KnowledgeTextEncodingError(KnowledgeTextParseError):
    """源文件无法按照约定的 UTF-8 编码严格解码。"""


class KnowledgeTextContentError(KnowledgeTextParseError):
    """文本为空，或包含当前不接受的 NUL 字符。"""


class KnowledgeTextTooLargeError(KnowledgeTextParseError):
    """规范化后的文本超过解析器允许的字符数量。"""


@dataclass(frozen=True)
class ParsedKnowledgeText:
    """解析结果，供后续切块和解析结果持久化使用。

    parser_name 和 parser_version 用于记录处理规则：
    将来修改规则后，可以判断历史结果是否需要重新生成。
    """

    text: str
    source_format: Literal["txt", "markdown"]
    parser_name: str = "utf8-text"
    parser_version: str = "1"


class KnowledgeTextParser:
    """只负责字节到文本的转换，不读文件、不写数据库。"""

    def __init__(self, *, max_text_chars: int = 1_000_000) -> None:
        # 配置错误属于调用方的问题，初始化时就应暴露。
        # 后续任务不能带着无效限制运行。
        if max_text_chars < 1:
            raise ValueError("Maximum text characters must be positive")

        self.max_text_chars = max_text_chars

    def parse(
        self,
        content: bytes,
        original_filename: str,
    ) -> ParsedKnowledgeText:
        """按照固定规则解析一个 TXT 或 Markdown 文件。"""

        source_format = self._source_format(original_filename)

        try:
            # utf-8-sig 同时接受普通 UTF-8 和开头带 BOM 的 UTF-8。
            # strict 遇到非法字节立即失败，避免悄悄丢掉或替换源内容。
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise KnowledgeTextEncodingError(
                "Source file must use valid UTF-8 encoding"
            ) from error

        # NUL 不属于当前支持的文本内容。
        # 这是一项内容规则，不能把它当作完整的二进制文件检测。
        if "\x00" in text:
            raise KnowledgeTextContentError(
                "Source text must not contain NUL characters"
            )

        # 先替换 CRLF，再处理剩下的 CR。
        # 反过来会把一个 CRLF 错误转换成两个换行。
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 按规范化后的字符数量限制后续切块工作量。
        # 这个限制不代替存储层对原始字节大小的限制。
        if len(text) > self.max_text_chars:
            raise KnowledgeTextTooLargeError(
                "Parsed text exceeds the configured character limit"
            )

        # strip() 只用于判空，不把结果赋值给 text。
        # 必须保留原始缩进、尾随空格及空行，避免改变 Markdown 内容。
        if not text.strip():
            raise KnowledgeTextContentError(
                "Source file contains no non-whitespace text"
            )

        return ParsedKnowledgeText(
            text=text,
            source_format=source_format,
        )

    @staticmethod
    def _source_format(
        original_filename: str,
    ) -> Literal["txt", "markdown"]:
        """根据后缀选择支持的文本格式，不访问文件系统。"""

        # 兼容元数据中可能出现的两种路径分隔符。
        # 此处只提取后缀，文件名绝不用于打开本机文件。
        filename = original_filename.replace("\\", "/").strip()
        suffix = PurePosixPath(filename).suffix.lower()

        if suffix == ".txt":
            return "txt"

        if suffix in {".md", ".markdown"}:
            return "markdown"

        raise UnsupportedKnowledgeTextFormatError(
            "Only TXT and Markdown source files are supported"
        )