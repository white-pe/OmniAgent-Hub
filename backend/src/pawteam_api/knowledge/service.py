"""Business operations for managed knowledge bases."""

from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from pawteam_api.models import KnowledgeBase


class KnowledgeBaseNotFoundError(LookupError):
    """Raised when a knowledge base does not exist."""


class KnowledgeBaseConflictError(ValueError):
    """Raised for duplicate names or stale updates."""


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[KnowledgeBaseResponse]:
        knowledge_bases = (
            await self.session.scalars(
                select(KnowledgeBase).order_by(
                    KnowledgeBase.created_at.desc(),
                    KnowledgeBase.name,
                )
            )
        ).all()
        return [self._response(item) for item in knowledge_bases]

    async def get(self, knowledge_base_id: str) -> KnowledgeBaseResponse:
        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
        )
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        return self._response(knowledge_base)

    async def create(
        self,
        payload: KnowledgeBaseCreate,
    ) -> KnowledgeBaseResponse:
        knowledge_base = KnowledgeBase(
            id=str(uuid4()),
            name=payload.name,
            description=payload.description,
        )
        self.session.add(knowledge_base)

        try:
            await self.session.commit()
            await self.session.refresh(knowledge_base)
        except IntegrityError as error:
            await self.session.rollback()
            raise KnowledgeBaseConflictError(
                "Knowledge base name already exists"
            ) from error

        return self._response(knowledge_base)

    async def update(
        self,
        knowledge_base_id: str,
        payload: KnowledgeBaseUpdate,
    ) -> KnowledgeBaseResponse:
        changes = payload.model_dump(
            exclude={"expected_version"},
            exclude_unset=True,
        )
        changes = {
            key: value
            for key, value in changes.items()
            if value is not None
        }

        if not changes:
            current = await self._get_model(knowledge_base_id)
            self._check_version(current, payload.expected_version)
            return self._response(current)

        statement = (
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.version == payload.expected_version,
            )
            .values(
                **changes,
                version=KnowledgeBase.version + 1,
                updated_at=func.now(),
            )
        )

        try:
            result = await self.session.execute(statement)
            if result.rowcount != 1:
                await self.session.rollback()
                current = await self._get_model(knowledge_base_id)
                self._check_version(current, payload.expected_version)
                raise KnowledgeBaseConflictError(
                    "Knowledge base changed; reload and retry"
                )
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise KnowledgeBaseConflictError(
                "Knowledge base name already exists"
            ) from error

        refreshed = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
            populate_existing=True,
        )
        if refreshed is None:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        return self._response(refreshed)

    async def delete(
        self,
        knowledge_base_id: str,
        expected_version: int,
    ) -> None:
        statement = delete(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.version == expected_version,
        )
        result = await self.session.execute(statement)

        if result.rowcount != 1:
            await self.session.rollback()
            current = await self._get_model(knowledge_base_id)
            self._check_version(current, expected_version)
            raise KnowledgeBaseConflictError(
                "Knowledge base changed; reload and retry"
            )

        await self.session.commit()

    async def _get_model(self, knowledge_base_id: str) -> KnowledgeBase:
        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
            populate_existing=True,
        )
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError(knowledge_base_id)
        return knowledge_base

    @staticmethod
    def _check_version(
        knowledge_base: KnowledgeBase,
        expected_version: int,
    ) -> None:
        if knowledge_base.version != expected_version:
            raise KnowledgeBaseConflictError(
                "Knowledge base changed; "
                f"current version is {knowledge_base.version}"
            )

    @staticmethod
    def _response(
        knowledge_base: KnowledgeBase,
    ) -> KnowledgeBaseResponse:
        return KnowledgeBaseResponse(
            id=knowledge_base.id,
            name=knowledge_base.name,
            description=knowledge_base.description,
            enabled=knowledge_base.enabled,
            version=knowledge_base.version,
            created_at=knowledge_base.created_at,
            updated_at=knowledge_base.updated_at,
        )