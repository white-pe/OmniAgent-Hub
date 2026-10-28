"""Business operations for knowledge documents."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pawteam_api.knowledge_schemas import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
)
from pawteam_api.models import KnowledgeBase, KnowledgeDocument


class KnowledgeDocumentKnowledgeBaseNotFoundError(LookupError):
    """Raised when a document's knowledge base does not exist."""


class KnowledgeDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> list[KnowledgeDocumentResponse]:
        await self._require_knowledge_base(knowledge_base_id)

        documents = (
            await self.session.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_base_id == knowledge_base_id
                )
                .order_by(
                    KnowledgeDocument.created_at.desc(),
                    KnowledgeDocument.title,
                )
            )
        ).all()

        return [self._response(document) for document in documents]

    async def create(
        self,
        knowledge_base_id: str,
        payload: KnowledgeDocumentCreate,
    ) -> KnowledgeDocumentResponse:
        await self._require_knowledge_base(knowledge_base_id)

        document = KnowledgeDocument(
            id=str(uuid4()),
            knowledge_base_id=knowledge_base_id,
            title=payload.title,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)

        return self._response(document)

    async def _require_knowledge_base(self, knowledge_base_id: str) -> None:
        knowledge_base = await self.session.get(
            KnowledgeBase,
            knowledge_base_id,
        )
        if knowledge_base is None:
            raise KnowledgeDocumentKnowledgeBaseNotFoundError(
                knowledge_base_id
            )

    @staticmethod
    def _response(
        document: KnowledgeDocument,
    ) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            title=document.title,
            status=document.status,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )