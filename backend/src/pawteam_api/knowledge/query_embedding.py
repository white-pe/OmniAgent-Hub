"""使用已有 Embedding Profile，为检索问题生成向量。"""

from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.knowledge.embedding_client import CompatibleEmbeddingClient
from pawteam_api.models import (
    KnowledgeEmbeddingProfile,
    Provider,
    ProviderModel,
)
from pawteam_api.security.secret_store import SecretStore


class QueryEmbeddingProfileNotFoundError(LookupError):
    """查询所选的 Profile 不存在。"""


class QueryEmbeddingConfigurationError(RuntimeError):
    """当前配置无法用于问题向量化。"""


@dataclass(frozen=True)
class QueryEmbeddingResult:
    """检索服务需要的查询向量，不作为文档向量落库。"""

    # 后续必须使用这个 Profile 对应的 Qdrant 集合。
    profile_id: str

    # 为下一步构建向量存储适配器提供维度信息。
    dimensions: int

    # 使用不可变 tuple，避免后续代码意外修改查询向量。
    vector: tuple[float, ...]


class KnowledgeQueryEmbeddingService:
    """读取配置、检查可用性，然后调用已有 Embedding 客户端。"""

    # 本平台对问题长度的保护值，单位是字符。
    # 它不等于模型的 Token 上限。
    max_query_chars = 4_000

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        secret_store: SecretStore,
        http_client: httpx.AsyncClient,
    ) -> None:
        # 保存组件引用，不保存跨调用共享的数据库 Session。
        self.session_factory = session_factory
        self.secret_store = secret_store
        self.http_client = http_client

    async def embed_query(
        self,
        *,
        profile_id: str,
        query: str,
    ) -> QueryEmbeddingResult:
        """为一条问题生成向量，不保存问题及向量。"""

        # 所有可以提前发现的输入问题，都在模型调用前拒绝。
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must contain non-blank text")

        if len(query) > self.max_query_chars:
            raise ValueError("Query exceeds the configured character limit")

        # 转成标准 UUID 字符串，非法 ID 会在查询数据库前失败。
        profile_id = str(UUID(profile_id))

        async with self.session_factory() as session:
            profile = await session.get(
                KnowledgeEmbeddingProfile,
                profile_id,
            )
            if profile is None:
                raise QueryEmbeddingProfileNotFoundError(
                    "Embedding profile not found"
                )

            # 当前文档向量使用原文输入，查询侧遵守同一份输入策略。
            # 将来支持其他模型的 query/document 前缀时，
            # 应实现新的策略，不能在这里偷偷修改 raw-v1 的语义。
            if profile.input_policy_version != "raw-v1":
                raise QueryEmbeddingConfigurationError(
                    "Unsupported embedding input policy"
                )

            provider = await session.get(
                Provider,
                profile.provider_id,
            )
            if (
                provider is None
                or not provider.enabled
                or provider.kind != "openai_compatible"
            ):
                raise QueryEmbeddingConfigurationError(
                    "Embedding provider is unavailable or unsupported"
                )

            # Profile 是创建时的快照。
            # Provider 地址变化后，不允许查询悄悄换用另一套模型服务。
            if (
                provider.base_url.rstrip("/")
                != profile.base_url.rstrip("/")
            ):
                raise QueryEmbeddingConfigurationError(
                    "Provider address no longer matches embedding profile"
                )

            # 模型必须仍然注册在此 Provider 下，并且处于启用状态。
            model_id = await session.scalar(
                select(ProviderModel.id).where(
                    ProviderModel.provider_id == provider.id,
                    ProviderModel.model_name == profile.model_name,
                    ProviderModel.enabled.is_(True),
                )
            )
            if model_id is None:
                raise QueryEmbeddingConfigurationError(
                    "Embedding model is not registered or enabled"
                )

            # 在 Session 关闭前提取普通值。
            # 网络调用阶段不再访问 ORM 对象或保持数据库事务。
            base_url = profile.base_url
            model_name = profile.model_name
            dimensions = profile.dimensions
            send_dimensions = profile.send_dimensions
            api_key_ref = provider.api_key_ref

        # 数据库读取会话已经关闭。
        # 密钥只在后端读取，不要求调用方重复提交。
        api_key = self.secret_store.get(api_key_ref)

        client = CompatibleEmbeddingClient(
            http_client=self.http_client,
            base_url=base_url,
            api_key=api_key,
        )

        # strip() 只用于前面的判空，不修改真实问题。
        # 使用已有客户端，复用数量、索引、维度和非零向量校验。
        batch = await client.embed(
            model=model_name,
            texts=[query],
            expected_dimensions=dimensions,
            send_dimensions=send_dimensions,
        )

        # 客户端已保证一条输入对应一条有效向量。
        return QueryEmbeddingResult(
            profile_id=profile_id,
            dimensions=dimensions,
            vector=tuple(batch.vectors[0]),
        )