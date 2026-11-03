"""Deterministic, source-offset-preserving text chunking."""

from dataclasses import dataclass

from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig


class KnowledgeChunkingInputError(ValueError):
    """切块输入为空或仅包含空白字符。"""


class KnowledgeChunkingLimitError(ValueError):
    """输入文本按当前配置会生成超过安全上限的片段。"""


# 限制单个切块批次的规模，避免极小 chunk_size 产生海量对象和数据库记录。
# 这是服务端保护阈值，不应由普通 API 请求参数覆盖。
MAX_CHUNKS_PER_SET = 5_000

@dataclass(frozen=True)
class KnowledgeTextChunk:
    """一个片段及其在规范化解析文本中的位置。"""

    chunk_index: int
    text: str
    start_char: int
    end_char: int

    @property
    def char_count(self) -> int:
        # 与数据库存储规则一致：长度是字符数，不是 UTF-8 字节数。
        return self.end_char - self.start_char


class KnowledgeTextChunker:
    """优先在段落、换行、空格处切分的确定性字符切块器。"""

    splitter_name = "boundary-character"
    splitter_version = "1"

    # 为每次切块设置服务端上限。放在算法类上，
    # 让解析出的文本无论来自 API 还是内部任务都会经过同一保护。
    max_chunks = MAX_CHUNKS_PER_SET

    # 顺序表示优先级：优先段落边界，其次普通换行，最后空格。
    # 每个分隔符都保留在对应 chunk 中，避免切块时丢失原文字符。
    _separators = ("\n\n", "\n", " ")

    def __init__(self, config: KnowledgeChunkingConfig) -> None:
        self.config = config

    def split(self, text: str) -> list[KnowledgeTextChunk]:
        """切分文本，并保证每块都能通过偏移量还原到原文。"""

        if not text or not text.strip():
            raise KnowledgeChunkingInputError(
                "Text must contain non-whitespace characters"
            )

        chunks: list[KnowledgeTextChunk] = []
        text_length = len(text)
        start = 0

        while start < text_length:
            # hard_end 是当前窗口允许的最大结束位置。
            # 即使长段落中没有任何分隔符，也绝不会超过 chunk_size。
            hard_end = min(
                start + self.config.chunk_size,
                text_length,
            )

            if hard_end == text_length:
                # 最后一块直接延伸到文本末尾，不再寻找边界。
                end = text_length
            else:
                end = self._find_preferred_boundary(
                    text=text,
                    start=start,
                    hard_end=hard_end,
                )

            # 防御性检查，避免错误边界导致死循环或生成空 chunk。
            if end <= start:
                raise RuntimeError("Chunk splitter failed to advance")

            chunk = KnowledgeTextChunk(
                chunk_index=len(chunks),
                text=text[start:end],
                start_char=start,
                end_char=end,
            )

            # 这是切块器最重要的不变量：
            # 每个 chunk 必须与它记录的原文切片完全相同。
            if chunk.text != text[chunk.start_char:chunk.end_char]:
                raise RuntimeError("Chunk text does not match source offsets")

            # 在追加新对象之前检查上限，避免超限后仍持续分配内存。
            # 已生成 max_chunks 个片段时，如果还有文本未处理，就拒绝整个任务。
            if len(chunks) >= self.max_chunks:
                raise KnowledgeChunkingLimitError(
                    f"Chunk count exceeds the limit of {self.max_chunks}"
                )

            chunks.append(chunk)

            if end == text_length:
                break

            # 下一个片段从当前片段末尾往前退 overlap 个字符开始。
            # 选取边界时会确保本块长度大于 overlap，因此 start 会前进。
            next_start = end - self.config.chunk_overlap
            if next_start <= start:
                raise RuntimeError("Chunk overlap prevents forward progress")

            start = next_start

        return chunks

    def _find_preferred_boundary(
        self,
        text: str,
        start: int,
        hard_end: int,
    ) -> int:
        """在窗口后半段按分隔符优先级寻找最后一个合适边界。"""

        # 不在窗口开头过早切分；同时要求本块长度大于 overlap，
        # 保证下一块起点一定向前移动，避免极端参数造成死循环。
        minimum_end = max(
            start + (self.config.chunk_size // 2),
            start + self.config.chunk_overlap + 1,
        )

        # 外层按分隔符优先级查找。
        # 因此即使换行更靠近 hard_end，只要窗口中有段落边界，
        # 仍然优先选择段落边界。
        for separator in self._separators:
            search_end = hard_end

            while search_end > minimum_end:
                position = text.rfind(
                    separator,
                    minimum_end,
                    search_end,
                )
                if position < 0:
                    break

                boundary = position + len(separator)

                # 分隔符必须完整落在当前窗口内，否则这次边界无效。
                if boundary <= hard_end:
                    return boundary

                # 继续向前找同类分隔符，排除越过 hard_end 的匹配。
                search_end = position

        # 没有找到合适边界，退化为硬切。
        return hard_end