"""Create embedding profiles and chunk vectors.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先创建配置表，再创建引用配置的向量表。
    op.create_table(
        "knowledge_embedding_profiles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_revision", sa.String(100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("send_dimensions", sa.Boolean(), nullable=False),
        sa.Column("input_policy_version", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "dimensions > 0",
            name="ck_knowledge_embedding_dimensions_positive",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "base_url",
            "model_name",
            "model_revision",
            "dimensions",
            "send_dimensions",
            "input_policy_version",
            name="uq_knowledge_embedding_profile_config",
        ),
    )
    op.create_index(
        "ix_knowledge_embedding_profiles_provider_id",
        "knowledge_embedding_profiles",
        ["provider_id"],
    )

    op.create_table(
        "knowledge_chunk_embeddings",
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("vector", sa.JSON(none_as_null=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("profile_id", "chunk_id"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["knowledge_embedding_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_embeddings_chunk_id",
        "knowledge_chunk_embeddings",
        ["chunk_id"],
    )


def downgrade() -> None:
    # 先删引用配置的向量表，再删配置表。
    op.drop_index(
        "ix_knowledge_chunk_embeddings_chunk_id",
        table_name="knowledge_chunk_embeddings",
    )
    op.drop_table("knowledge_chunk_embeddings")

    op.drop_index(
        "ix_knowledge_embedding_profiles_provider_id",
        table_name="knowledge_embedding_profiles",
    )
    op.drop_table("knowledge_embedding_profiles")