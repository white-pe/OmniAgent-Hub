"""HTTP adapter for OpenAI-compatible embedding endpoints."""

from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from pawteam_api.knowledge.embeddings import EmbeddingBatch


class EmbeddingRequestError(RuntimeError):
    """网络请求或上游 HTTP 状态失败。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)

        # 保留结构化状态码，供后续任务层判断是否允许重试。
        # 不把密钥、请求正文或上游响应正文拼进异常信息。
        self.status_code = status_code


class EmbeddingResponseError(RuntimeError):
    """请求已成功，但返回的数据不能作为有效向量使用。"""


class _EmbeddingItem(BaseModel):
    """协议内部模型，不直接作为平台 API 响应。"""

    # 上游可能附带 object 等字段，我们只解析需要的部分。
    # 已声明的字段使用严格校验，拒绝字符串索引、布尔值等。
    model_config = ConfigDict(strict=True, extra="ignore")

    index: int = Field(ge=0)
    embedding: list[FiniteFloat] = Field(min_length=1)


class _EmbeddingResponse(BaseModel):
    """只声明本适配器当前依赖的响应字段。"""

    model_config = ConfigDict(strict=True, extra="ignore")

    data: list[_EmbeddingItem] = Field(min_length=1)


class CompatibleEmbeddingClient:
    """把兼容接口响应转换为本项目统一的 EmbeddingBatch。"""

    # 这是本项目的单次请求保护值，不是模型厂商的统一上限。
    # 后续批量 Service 应主动分批，不应把整个切块批次一次发送。
    max_batch_size = 64
    max_total_chars = 100_000

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Embedding timeout must be positive")

        # base_url 由后续模型配置提供，例如：
        # https://provider.example/v1
        # 这里负责补上资源路径，调用方不要传完整的 /embeddings 地址。
        url = httpx.URL(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("Invalid embedding base URL")

        self.endpoint = f"{str(url).rstrip('/')}/embeddings"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
        }
        self.timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(timeout_seconds, 10.0),
        )

        # 连接由调用方创建和关闭。
        # 以后应用生命周期可以复用连接池，测试则注入模拟客户端。
        self.http_client = http_client

    async def embed(
        self,
        *,
        model: str,
        texts: list[str],
        expected_dimensions: int,
        send_dimensions: bool = False,
    ) -> EmbeddingBatch:
        """生成一批向量，返回顺序必须与 texts 完全一致。"""

        self._validate_input(model, texts, expected_dimensions)

        payload: dict[str, object] = {
            "model": model,
            "input": texts,
            "encoding_format": "float",
        }

        # 只有确认上游支持这个参数时才发送。
        # 无论是否发送，收到向量后都必须检查 expected_dimensions。
        if send_dimensions:
            payload["dimensions"] = expected_dimensions

        try:
            response = await self.http_client.post(
                self.endpoint,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
                # 重定向不属于当前适配器的成功协议。
                follow_redirects=False,
            )
        except httpx.TimeoutException as error:
            raise EmbeddingRequestError(
                "Embedding request timed out"
            ) from error
        except httpx.RequestError as error:
            raise EmbeddingRequestError(
                "Embedding provider connection failed"
            ) from error

        if not response.is_success:
            # 不直接使用上游响应正文：
            # 正文可能包含内部网关信息、输入文本或其他敏感内容。
            raise EmbeddingRequestError(
                f"Embedding provider returned HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            parsed = _EmbeddingResponse.model_validate(response.json())
        except ValueError as error:
            # JSON 解码失败和 Pydantic ValidationError 都会进入这里。
            raise EmbeddingResponseError(
                "Embedding provider returned invalid response data"
            ) from error

        input_count = len(texts)

        if len(parsed.data) != input_count:
            # 数量不一致时不能猜测哪条文本缺失，更不能补零向量。
            raise EmbeddingResponseError(
                "Embedding response count does not match input count"
            )

        indexes = [item.index for item in parsed.data]

        # 同时排除重复、缺失、越界索引。
        # 例如输入两条文本时，唯一合法索引集合就是 {0, 1}。
        if set(indexes) != set(range(input_count)):
            raise EmbeddingResponseError(
                "Embedding response indexes are invalid"
            )

        # 不能依赖上游数组的实际排列顺序。
        # 用 index 恢复对应关系，避免把 A 文本关联到 B 的向量。
        ordered = sorted(parsed.data, key=lambda item: item.index)

        try:
            return EmbeddingBatch(
                dimensions=expected_dimensions,
                vectors=[item.embedding for item in ordered],
            )
        except ValueError as error:
            # 复用上一轮建立的统一校验：
            # 拒绝维度不一致、零向量等不符合索引要求的数据。
            raise EmbeddingResponseError(
                "Embedding vectors failed validation"
            ) from error

    @classmethod
    def _validate_input(
        cls: type[Self],
        model: str,
        texts: list[str],
        expected_dimensions: int,
    ) -> None:
        """输入错误在发出请求前暴露，避免无效调用。"""

        if not isinstance(model, str) or not model.strip():
            raise ValueError("Embedding model must not be blank")

        # bool 是 int 的子类，因此这里使用精确类型判断。
        if type(expected_dimensions) is not int or expected_dimensions < 1:
            raise ValueError("Expected dimensions must be a positive integer")

        if not isinstance(texts, list) or not 1 <= len(texts) <= cls.max_batch_size:
            raise ValueError(
                f"Embedding input count must be between 1 and {cls.max_batch_size}"
            )

        total_chars = 0
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Embedding inputs must contain non-blank text")

            # strip() 只用于判空，不修改真实输入。
            total_chars += len(text)

        if total_chars > cls.max_total_chars:
            raise ValueError(
                "Embedding inputs exceed the configured character limit"
            )