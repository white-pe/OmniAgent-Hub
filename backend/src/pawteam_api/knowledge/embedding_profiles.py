"""Create and query immutable embedding profile configurations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.knowledge_schemas import (
    KnowledgeEmbeddingProfileCreate,
    KnowledgeEmbeddingProfileResponse,
)
from pawteam_api.models import (
    KnowledgeEmbeddingProfile,
    Provider,
    ProviderModel,
)


class EmbeddingProfileNotFoundError(LookupError):
    """指定的 Profile、Provider 或模型不存在。"""


class EmbeddingProfileConflictError(ValueError):
    """Provider 或模型当前不可用于创建配置。"""


class KnowledgeEmbeddingProfileService:
    def __init__(self, session: AsyncSession) -> None:
        # 与现有 Provider 服务保持一致，由请求依赖提供 Session。
        self.session = session

    async def get(
        self,
        profile_id: str,
    ) -> KnowledgeEmbeddingProfileResponse:
        """读取配置快照；Provider 被禁用后仍允许查看历史配置。"""

        profile = await self.session.get(
            KnowledgeEmbeddingProfile,
            str(UUID(profile_id)),
        )
        if profile is None:
            raise EmbeddingProfileNotFoundError(
                "Embedding profile not found"
            )

        return KnowledgeEmbeddingProfileResponse.model_validate(profile)

    async def list(
        self,
        *,
        provider_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[KnowledgeEmbeddingProfileResponse]:
        """分页查询配置，可按 Provider 筛选。"""

        # 内部调用也遵守限制，不能只依赖 HTTP 参数校验。
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("Offset must be nonnegative")

        statement = select(KnowledgeEmbeddingProfile)

        if provider_id is not None:
            statement = statement.where(
                KnowledgeEmbeddingProfile.provider_id
                == str(UUID(provider_id))
            )

        records = (
            await self.session.scalars(
                statement.order_by(
                    KnowledgeEmbeddingProfile.created_at.desc(),
                    KnowledgeEmbeddingProfile.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()

        return [
            KnowledgeEmbeddingProfileResponse.model_validate(record)
            for record in records
        ]

    async def create(
        self,
        payload: KnowledgeEmbeddingProfileCreate,
    ) -> KnowledgeEmbeddingProfileResponse:
        """相同配置复用已有 Profile，不修改已经创建的配置。"""

        provider = await self.session.get(
            Provider,
            str(payload.provider_id),
        )
        if provider is None:
            raise EmbeddingProfileNotFoundError("Provider not found")

        if not provider.enabled or provider.kind != "openai_compatible":
            raise EmbeddingProfileConflictError(
                "Provider is disabled or unsupported"
            )

        # 同时约束 model_id 和 provider_id。
        # 不能把其他 Provider 下的模型绑定到当前配置。
        model = await self.session.scalar(
            select(ProviderModel).where(
                ProviderModel.id == str(payload.model_id),
                ProviderModel.provider_id == provider.id,
            )
        )
        if model is None:
            raise EmbeddingProfileNotFoundError(
                "Model not found under this provider"
            )
        if not model.enabled:
            raise EmbeddingProfileConflictError("Model is disabled")

        # 只保存配置快照，不复制密钥。
        # 字段组合与数据库唯一约束保持一致。
        configuration: dict[str, object] = {
            "provider_id": provider.id,
            "base_url": provider.base_url.rstrip("/"),
            "model_name": model.model_name,
            "model_revision": payload.model_revision,
            "dimensions": payload.dimensions,
            "send_dimensions": payload.send_dimensions,
            "input_policy_version": payload.input_policy_version,
        }

        existing = await self._find(configuration)
        if existing is not None:
            return KnowledgeEmbeddingProfileResponse.model_validate(existing)

        profile = KnowledgeEmbeddingProfile(**configuration)
        self.session.add(profile)

        try:
            await self.session.commit()
        except IntegrityError:
            # 两个相同请求可能同时查不到记录，然后竞争唯一键。
            # 先回滚失败事务，再检查另一请求是否已经创建成功。
            await self.session.rollback()
            existing = await self._find(configuration)

            if existing is not None:
                return KnowledgeEmbeddingProfileResponse.model_validate(
                    existing
                )

            # 不是相同配置的并发创建，保留真实数据库错误。
            raise

        await self.session.refresh(profile)
        return KnowledgeEmbeddingProfileResponse.model_validate(profile)

    async def _find(
        self,
        configuration: dict[str, object],
    ) -> KnowledgeEmbeddingProfile | None:
        """使用完整唯一配置查找，不能只根据模型名判断相同。"""

        return await self.session.scalar(
            select(KnowledgeEmbeddingProfile).filter_by(**configuration)
        )