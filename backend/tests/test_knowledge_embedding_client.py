import json

import httpx
import pytest

from pawteam_api.knowledge.embedding_client import (
    CompatibleEmbeddingClient,
    EmbeddingRequestError,
    EmbeddingResponseError,
)


def make_client(http_client: httpx.AsyncClient) -> CompatibleEmbeddingClient:
    """测试只使用模拟地址和假密钥，不发送真实网络请求。"""

    return CompatibleEmbeddingClient(
        http_client=http_client,
        base_url="https://embedding.example/v1/",
        api_key="test-key",
    )


@pytest.mark.parametrize("send_dimensions", [False, True])
async def test_embeds_texts_and_restores_input_order(
    send_dimensions: bool,
) -> None:
    """验证请求内容、可选维度参数，以及返回乱序时的映射。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://embedding.example/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer test-key"

        payload = json.loads(request.content)
        assert payload["model"] == "test-embedding"
        assert payload["input"] == ["first text", "second text"]
        assert payload["encoding_format"] == "float"

        if send_dimensions:
            assert payload["dimensions"] == 2
        else:
            assert "dimensions" not in payload

        # 故意先返回第二条向量。
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        result = await make_client(http_client).embed(
            model="test-embedding",
            texts=["first text", "second text"],
            expected_dimensions=2,
            send_dimensions=send_dimensions,
        )

    assert result.dimensions == 2
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"data": []},
        # 输入两条，返回一条。
        {"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        # 重复索引。
        {"data": [
            {"index": 0, "embedding": [1.0, 0.0]},
            {"index": 0, "embedding": [0.0, 1.0]},
        ]},
        # 越界索引。
        {"data": [
            {"index": 0, "embedding": [1.0, 0.0]},
            {"index": 2, "embedding": [0.0, 1.0]},
        ]},
        # bool 不能作为合法索引。
        {"data": [
            {"index": False, "embedding": [1.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ]},
        # 不接受字符串索引。
        {"data": [
            {"index": "0", "embedding": [1.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ]},
        # 第一条维度错误。
        {"data": [
            {"index": 0, "embedding": [1.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ]},
        # 第一条是零向量。
        {"data": [
            {"index": 0, "embedding": [0.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ]},
        # 不允许把字符串自动转换成向量数值。
        {"data": [
            {"index": 0, "embedding": ["1.0", 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ]},
    ],
)
async def test_rejects_invalid_response(body: object) -> None:
    """协议错误不能被误认为成功的向量化结果。"""

    def handler(request: httpx.Request) -> httpx.Response:
        # 显式编码 None，确保该用例返回 JSON null。
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        with pytest.raises(EmbeddingResponseError):
            await make_client(http_client).embed(
                model="test-embedding",
                texts=["first", "second"],
                expected_dimensions=2,
            )


@pytest.mark.parametrize("status_code", [400, 401, 429, 503])
async def test_http_errors_keep_status_without_exposing_body(
    status_code: int,
) -> None:
    """任务层能读取状态码，但公开错误消息不能包含上游正文。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            text="private upstream information",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        with pytest.raises(EmbeddingRequestError) as captured:
            await make_client(http_client).embed(
                model="test-embedding",
                texts=["first"],
                expected_dimensions=2,
            )

    assert captured.value.status_code == status_code
    assert "private upstream information" not in str(captured.value)


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadTimeout, httpx.ConnectError],
)
async def test_transport_errors_are_translated(
    error_type: type[httpx.RequestError],
) -> None:
    """超时和连接错误都转换成统一请求异常。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("private network detail", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        with pytest.raises(EmbeddingRequestError) as captured:
            await make_client(http_client).embed(
                model="test-embedding",
                texts=["first"],
                expected_dimensions=2,
            )

    assert captured.value.status_code is None
    assert "private network detail" not in str(captured.value)


@pytest.mark.parametrize(
    "texts",
    [
        [],
        ["   "],
        ["valid", 42],
        ["x"] * 65,
        ["x" * 100_001],
    ],
)
async def test_invalid_input_never_sends_request(texts: object) -> None:
    """本地输入错误必须在访问上游之前失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input unexpectedly sent an HTTP request")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        with pytest.raises(ValueError):
            await make_client(http_client).embed(
                model="test-embedding",
                texts=texts,
                expected_dimensions=2,
            )


async def test_rejects_non_json_success_response() -> None:
    """HTTP 200 不等于业务成功，HTML 等内容仍然必须拒绝。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        with pytest.raises(EmbeddingResponseError):
            await make_client(http_client).embed(
                model="test-embedding",
                texts=["first"],
                expected_dimensions=2,
            )