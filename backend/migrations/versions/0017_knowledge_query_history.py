"""Persist each Knowledge search and cited answer as a separate history entry."""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_query_history",
        sa.Column(
            "request_id",
            sa.String(36),
            sa.ForeignKey("knowledge_query_logs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_knowledge_query_history_created_at",
        "knowledge_query_history",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_query_history")
