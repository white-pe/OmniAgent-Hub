import json

import httpx
import pytest

from pawteam_api.knowledge.embedding_client import (
    CompatibleEmbeddingClient,
    EmbeddingRequestError,
)
from pawteam_api.knowledge.embedding_service import (
    EmbeddingChunkInput,
    KnowledgeEmbeddingService,
)


def make_service(
    http_client: httpx.AsyncClient,
    *,
    batch_size: int = 2,
    max_batch_chars: int = 100,
) -> KnowledgeEmbeddingService:
    """复用真实客户端，只模拟网络边界。"""

    client = CompatibleEmbeddingClient(
        http_client=http_client,
        base_url="https://embedding.example/v1",
        api_key="test-key",
    )
    return KnowledgeEmbeddingService(
        client=client,
        model="test-embedding",
        expected_dimensions=2,
        batch_size=batch_size,
        max_batch_chars=max_batch_chars,
    )


def successful_response(texts: list[str]) -> httpx.Response:
    """用文本中的数字构造可识别的向量，并故意反序返回。"""

    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "index": index,
                    "embedding": [float(text), 1.0],
                }
                for index, text in reversed(list(enumerate(texts)))
            ]
        },
    )


async def test_splits_by_count_and_preserves_chunk_mapping() -> None:
    """跨批次后，片段 ID 与向量仍必须严格对应。"""

    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        requests.append(texts)
        return successful_response(texts)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        result = await make_service(http_client).embed_chunks(
            [
                EmbeddingChunkInput(f"chunk-{index}", str(index))
                for index in range(5)
            ]
        )

    assert requests == [["0", "1"], ["2", "3"], ["4"]]
    assert [item.chunk_id for item in result] == [
        f"chunk-{index}" for index in range(5)
    ]
    assert [item.vector for item in result] == [
        (float(index), 1.0) for index in range(5)
    ]


async def test_splits_by_character_budget() -> None:
    """未达到条数限制，也可能因为字符数而提前分批。"""

    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        requests.append(texts)
        return successful_response(texts)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        await make_service(
            http_client,
            batch_size=10,
            max_batch_chars=4,
        ).embed_chunks(
            [
                EmbeddingChunkInput("a", "11"),
                EmbeddingChunkInput("b", "22"),
                EmbeddingChunkInput("c", "33"),
            ]
        )

    # 恰好达到 4 个字符可以通过，多一个片段就要另开一批。
    assert requests == [["11", "22"], ["33"]]


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [
            EmbeddingChunkInput("same", "1"),
            EmbeddingChunkInput("same", "2"),
        ],
        [
            EmbeddingChunkInput("a", "1"),
            EmbeddingChunkInput("b", " "),
        ],
        [
            EmbeddingChunkInput("a", "1"),
            EmbeddingChunkInput("", "2"),
        ],
        [
            EmbeddingChunkInput("a", "1"),
            EmbeddingChunkInput("b", "12345"),
        ],
    ],
)
async def test_all_input_is_validated_before_first_request(
    chunks: list[EmbeddingChunkInput],
) -> None:
    """即使错误在最后一个片段，也不能先发送前面的批次。"""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input unexpectedly sent a request")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        service = make_service(
            http_client,
            batch_size=1,
            max_batch_chars=4,
        )
        with pytest.raises(ValueError):
            await service.embed_chunks(chunks)


async def test_stops_after_upstream_failure() -> None:
    """第二批失败后立即停止，不发送第三批，也不返回部分结果。"""

    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        requests.append(texts)

        if len(requests) == 2:
            return httpx.Response(429, text="rate limited")

        return successful_response(texts)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        service = make_service(http_client, batch_size=1)

        with pytest.raises(EmbeddingRequestError) as captured:
            await service.embed_chunks(
                [
                    EmbeddingChunkInput("a", "1"),
                    EmbeddingChunkInput("b", "2"),
                    EmbeddingChunkInput("c", "3"),
                ]
            )

    assert captured.value.status_code == 429
    assert requests == [["1"], ["2"]]