import pytest
from pydantic import ValidationError

from pawteam_api.knowledge_schemas import KnowledgeDocumentCreate


def test_document_create_normalizes_title() -> None:
    payload = KnowledgeDocumentCreate(title="  API Guide  ")

    assert payload.title == "API Guide"


def test_document_create_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDocumentCreate(title="   ")


def test_document_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDocumentCreate(
            title="API Guide",
            storage_key="../../outside",
        )


@pytest.mark.parametrize("title", ["", "x" * 201])
def test_document_create_rejects_invalid_title_length(title: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeDocumentCreate(title=title)