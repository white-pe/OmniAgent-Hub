"""Create explicit Agent-to-knowledge-base bindings.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_knowledge_bindings",
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "agent_id",
            "knowledge_base_id",
            name="pk_agent_knowledge_bindings",
        ),
    )
    op.create_index(
        "ix_agent_knowledge_bindings_knowledge_base_id",
        "agent_knowledge_bindings",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_knowledge_bindings_knowledge_base_id",
        table_name="agent_knowledge_bindings",
    )
    op.drop_table("agent_knowledge_bindings")