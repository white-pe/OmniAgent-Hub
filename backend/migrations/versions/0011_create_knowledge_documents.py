"""Create knowledge documents and immutable source versions.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_knowledge_base_id",
        "knowledge_documents",
        ["knowledge_base_id"],
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_knowledge_document_version_positive",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_knowledge_document_version_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_knowledge_document_version_number",
        ),
    )
    op.create_index(
        "ix_knowledge_document_versions_document_id",
        "knowledge_document_versions",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_document_versions_document_id",
        table_name="knowledge_document_versions",
    )
    op.drop_table("knowledge_document_versions")
    op.drop_index(
        "ix_knowledge_documents_knowledge_base_id",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")