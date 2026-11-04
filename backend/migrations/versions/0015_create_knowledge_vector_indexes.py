"""Create persistent Qdrant indexing state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 Qdrant 索引状态表及 worker 查找索引。"""

    op.create_table(
        "knowledge_vector_indexes",
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("chunk_set_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "expected_points",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "indexed_points",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'indexing', 'indexed', 'failed')",
            name="ck_knowledge_vector_index_status",
        ),
        sa.CheckConstraint(
            "expected_points >= 0 AND indexed_points >= 0",
            name="ck_knowledge_vector_index_points_nonnegative",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_knowledge_vector_index_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "indexed_points <= expected_points",
            name="ck_knowledge_vector_index_points_within_expected",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["knowledge_embedding_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_set_id"],
            ["knowledge_chunk_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "chunk_set_id"),
    )

    op.create_index(
        "ix_knowledge_vector_indexes_status_lease",
        "knowledge_vector_indexes",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    """回滚时先删除索引，再删除状态表。"""

    op.drop_index(
        "ix_knowledge_vector_indexes_status_lease",
        table_name="knowledge_vector_indexes",
    )
    op.drop_table("knowledge_vector_indexes")