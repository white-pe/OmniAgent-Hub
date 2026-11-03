"""Create chunk sets and traceable text chunks.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先创建批次，再创建引用批次的片段表。
    op.create_table(
        "knowledge_chunk_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("source_text_sha256", sa.String(64), nullable=False),
        sa.Column("splitter_name", sa.String(100), nullable=False),
        sa.Column("splitter_version", sa.String(30), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_size > 0",
            name="ck_knowledge_chunk_set_size_positive",
        ),
        sa.CheckConstraint(
            "chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_knowledge_chunk_set_overlap_valid",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_document_parse_results.version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id",
            "source_text_sha256",
            "splitter_name",
            "splitter_version",
            "chunk_size",
            "chunk_overlap",
            name="uq_knowledge_chunk_set_config",
        ),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("chunk_set_id", sa.String(36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "start_char >= 0 AND end_char > start_char",
            name="ck_knowledge_chunk_offsets_valid",
        ),
        sa.CheckConstraint(
            "char_count = end_char - start_char",
            name="ck_knowledge_chunk_char_count_matches_span",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_set_id"],
            ["knowledge_chunk_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chunk_set_id",
            "chunk_index",
            name="uq_knowledge_chunk_set_index",
        ),
    )


def downgrade() -> None:
    # 回滚顺序与创建顺序相反，先删子表。
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_chunk_sets")