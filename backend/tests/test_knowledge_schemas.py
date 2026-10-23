import pytest
from pawteam_api.knowledge_schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)
from pydantic import ValidationError


def test_create_normalizes_name_and_description() -> None:
    payload = KnowledgeBaseCreate(
        name="  Engineering Docs  ",
        description="  Internal references  ",
    )

    assert payload.name == "Engineering Docs"
    assert payload.description == "Internal references"


def test_create_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBaseCreate(name="   ")


def test_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBaseCreate(name="Engineering Docs", enabled=False)


def test_update_tracks_explicitly_submitted_fields() -> None:
    payload = KnowledgeBaseUpdate(
        expected_version=3,
        description="",
    )

    assert payload.model_fields_set == {"expected_version", "description"}
    assert payload.description == ""


def test_update_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBaseUpdate(expected_version=1, name="   ")