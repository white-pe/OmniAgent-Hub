"""Create Agent metadata linked to Provider and Model.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("workspace_path", sa.String(length=500), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("is_coordinator", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
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
            ["model_id"], ["provider_models.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("workspace_path"),
    )
    op.create_index(op.f("ix_agents_model_id"), "agents", ["model_id"], unique=False)
    op.create_index(
        op.f("ix_agents_provider_id"), "agents", ["provider_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_provider_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_model_id"), table_name="agents")
    op.drop_table("agents")
