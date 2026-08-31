"""Create reviewable Agent Blueprint drafts.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_blueprint_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_text", sa.String(length=4000), nullable=False),
        sa.Column("source_provider_id", sa.String(length=36), nullable=False),
        sa.Column("source_model_id", sa.String(length=36), nullable=False),
        sa.Column("blueprint_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("applied_agent_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["applied_agent_id"], ["agents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_model_id"], ["provider_models.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_provider_id"], ["providers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_blueprint_drafts_applied_agent_id"),
        "agent_blueprint_drafts",
        ["applied_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_blueprint_drafts_source_model_id"),
        "agent_blueprint_drafts",
        ["source_model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_blueprint_drafts_source_provider_id"),
        "agent_blueprint_drafts",
        ["source_provider_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_blueprint_drafts_source_provider_id"),
        table_name="agent_blueprint_drafts",
    )
    op.drop_index(
        op.f("ix_agent_blueprint_drafts_source_model_id"),
        table_name="agent_blueprint_drafts",
    )
    op.drop_index(
        op.f("ix_agent_blueprint_drafts_applied_agent_id"),
        table_name="agent_blueprint_drafts",
    )
    op.drop_table("agent_blueprint_drafts")
