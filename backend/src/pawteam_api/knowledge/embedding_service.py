"""Batch chunk embeddings while preserving chunk identity."""

from dataclasses import dataclass

from pawteam_api.knowledge.embedding_client import (
    CompatibleEmbeddingClient,
    EmbeddingResponseError,
)


@dataclass(frozen=True)
class EmbeddingChunkInput:
    """向量化输入：始终让片段 ID 与正文一起传递。"""

    chunk_id: str
    text: str


@dataclass(frozen=True)
class EmbeddedChunk:
    """一个片段与它对应的向量。"""

    chunk_id: str

    # 使用 tuple，避免调用方意外修改已经得到的向量。
    vector: tuple[float, ...]


class KnowledgeEmbeddingService:
    """规划分批请求，并把模型向量重新关联到片段 ID。"""

    # 当前一次处理一组切块产物。
    # 限制整体输入规模，不能只限制每次 HTTP 请求的规模。
    max_input_chunks = 5_000
    max_input_chars = 1_000_000

    def __init__(
        self,
        *,
        client: CompatibleEmbeddingClient,
        model: str,
        expected_dimensions: int,
        batch_size: int = 32,
        max_batch_chars: int = 50_000,
        send_dimensions: bool = False,
    ) -> None:
        # 配置错误应在调用模型之前暴露。
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Embedding model must not be blank")

        if type(expected_dimensions) is not int or expected_dimensions < 1:
            raise ValueError("Expected dimensions must be a positive integer")

        # Service 的请求规模不能超过客户端已有的保护上限。
        if (
            type(batch_size) is not int
            or not 1 <= batch_size <= client.max_batch_size
        ):
            raise ValueError("Invalid embedding batch size")

        if (
            type(max_batch_chars) is not int
            or not 1 <= max_batch_chars <= client.max_total_chars
        ):
            raise ValueError("Invalid embedding batch character limit")

        if type(send_dimensions) is not bool:
            raise ValueError("Send dimensions must be a boolean")

        self.client = client
        self.model = model
        self.expected_dimensions = expected_dimensions
        self.batch_size = batch_size
        self.max_batch_chars = max_batch_chars
        self.send_dimensions = send_dimensions

    async def embed_chunks(
        self,
        chunks: list[EmbeddingChunkInput],
    ) -> list[EmbeddedChunk]:
        """全部请求成功后返回结果；任意一批失败则抛出异常。"""

        # 先完成全部校验和分批，之后才发送第一个请求。
        # 避免处理到最后才发现重复 ID 或某条文本过长。
        batches = self._plan_batches(chunks)
        results: list[EmbeddedChunk] = []

        for batch in batches:
            # 顺序调用，先建立容易理解、可验证的处理流程。
            # 本轮不并发请求，也不在这里自动重试。
            response = await self.client.embed(
                model=self.model,
                texts=[chunk.text for chunk in batch],
                expected_dimensions=self.expected_dimensions,
                send_dimensions=self.send_dimensions,
            )

            # 客户端已经验证这些条件，这里明确批处理依赖的契约。
            # 将来替换适配器时，也不能静默接受数量或维度不一致。
            if (
                response.dimensions != self.expected_dimensions
                or len(response.vectors) != len(batch)
            ):
                raise EmbeddingResponseError(
                    "Embedding batch does not match the planned request"
                )

            # 客户端保证 vectors 与输入文本顺序一致。
            # 这里使用同一批输入顺序，将向量关联回片段 ID。
            for chunk, vector in zip(
                batch,
                response.vectors,
                strict=True,
            ):
                results.append(
                    EmbeddedChunk(
                        chunk_id=chunk.chunk_id,
                        vector=tuple(vector),
                    )
                )

        # 只有所有批次成功，调用方才能拿到完整结果。
        # 注意：这不代表此前的外部模型调用可以回滚。
        return results

    def _plan_batches(
        self,
        chunks: list[EmbeddingChunkInput],
    ) -> list[list[EmbeddingChunkInput]]:
        """按条数和字符数双重限制分批，保持原有顺序。"""

        if (
            not isinstance(chunks, list)
            or not 1 <= len(chunks) <= self.max_input_chunks
        ):
            raise ValueError("Invalid embedding chunk count")

        # 复制列表结构；输入项使用 frozen dataclass。
        # 调用方后续改变原列表，不影响已经生成的请求计划。
        snapshot = tuple(chunks)

        seen_ids: set[str] = set()
        total_chars = 0

        # 第一遍验证全部输入，期间不发起网络请求。
        for chunk in snapshot:
            if not isinstance(chunk, EmbeddingChunkInput):
                raise ValueError("Invalid embedding chunk input")

            if not isinstance(chunk.chunk_id, str) or not chunk.chunk_id.strip():
                raise ValueError("Chunk ID must not be blank")

            if chunk.chunk_id in seen_ids:
                raise ValueError("Duplicate chunk ID")
            seen_ids.add(chunk.chunk_id)

            if not isinstance(chunk.text, str) or not chunk.text.strip():
                raise ValueError("Chunk text must not be blank")

            # 单个片段超限时直接拒绝，不在这里再次切分。
            # 再切分会改变片段与向量一一对应的关系。
            if len(chunk.text) > self.max_batch_chars:
                raise ValueError("Single chunk exceeds batch character limit")

            total_chars += len(chunk.text)
            if total_chars > self.max_input_chars:
                raise ValueError("Embedding job exceeds character limit")

        batches: list[list[EmbeddingChunkInput]] = []
        current: list[EmbeddingChunkInput] = []
        current_chars = 0

        # 第二遍规划批次。
        for chunk in snapshot:
            would_exceed_chars = (
                current_chars + len(chunk.text) > self.max_batch_chars
            )
            reached_item_limit = len(current) >= self.batch_size

            if current and (would_exceed_chars or reached_item_limit):
                batches.append(current)
                current = []
                current_chars = 0

            current.append(chunk)
            current_chars += len(chunk.text)

        if current:
            batches.append(current)

        return batches