"""Create Channel adapters, external conversation mappings, and message queue.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("secret_ref", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("secret_ref"),
    )
    op.create_index(
        op.f("ix_channels_agent_id"), "channels", ["agent_id"], unique=False
    )

    op.create_table(
        "external_conversations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("external_conversation_id", sa.String(200), nullable=False),
        sa.Column("external_user_id", sa.String(200), nullable=False),
        sa.Column("chat_session_id", sa.String(36), nullable=False),
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
            ["channel_id"], ["channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_session_id"),
        sa.UniqueConstraint(
            "channel_id",
            "external_conversation_id",
            name="uq_channel_external_conversation",
        ),
    )
    op.create_index(
        op.f("ix_external_conversations_channel_id"),
        "external_conversations",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_conversations_chat_session_id"),
        "external_conversations",
        ["chat_session_id"],
        unique=True,
    )

    op.create_table(
        "channel_messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("external_conversation_id", sa.String(200), nullable=False),
        sa.Column("external_user_id", sa.String(200), nullable=False),
        sa.Column("external_message_id", sa.String(200), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("chat_session_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
            ["channel_id"], ["channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "direction",
            "external_message_id",
            name="uq_channel_direction_external_message",
        ),
    )
    for column in (
        "channel_id",
        "external_conversation_id",
        "chat_session_id",
        "run_id",
    ):
        op.create_index(
            op.f(f"ix_channel_messages_{column}"),
            "channel_messages",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "run_id",
        "chat_session_id",
        "external_conversation_id",
        "channel_id",
    ):
        op.drop_index(op.f(f"ix_channel_messages_{column}"), table_name="channel_messages")
    op.drop_table("channel_messages")
    op.drop_index(
        op.f("ix_external_conversations_chat_session_id"),
        table_name="external_conversations",
    )
    op.drop_index(
        op.f("ix_external_conversations_channel_id"),
        table_name="external_conversations",
    )
    op.drop_table("external_conversations")
    op.drop_index(op.f("ix_channels_agent_id"), table_name="channels")
    op.drop_table("channels")
