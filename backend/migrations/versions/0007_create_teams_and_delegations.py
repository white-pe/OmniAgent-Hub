"""Create Teams, membership, and durable Agent delegation records.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_runs_one_active_per_session", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("parent_run_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column("depth", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_foreign_key(
            "fk_runs_parent_run_id",
            "runs",
            ["parent_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_runs_parent_run_id", ["parent_run_id"])
    op.create_index(
        "uq_runs_one_active_per_session",
        "runs",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text(
            "parent_run_id IS NULL AND status IN ('queued', 'running', 'cancelling')"
        ),
    )

    op.create_table(
        "teams",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("coordinator_agent_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
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
            ["coordinator_agent_id"], ["agents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        op.f("ix_teams_coordinator_agent_id"),
        "teams",
        ["coordinator_agent_id"],
        unique=False,
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "agent_id", name="uq_team_member_agent"),
    )
    op.create_index(
        op.f("ix_team_members_agent_id"),
        "team_members",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_members_team_id"),
        "team_members",
        ["team_id"],
        unique=False,
    )

    op.create_table(
        "delegations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("parent_run_id", sa.String(36), nullable=False),
        sa.Column("root_run_id", sa.String(36), nullable=False),
        sa.Column("child_run_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=False),
        sa.Column("source_agent_id", sa.String(36), nullable=False),
        sa.Column("target_agent_id", sa.String(36), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["child_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_agent_id"], ["agents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_id"], ["agents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_delegations_child_run_id"),
        "delegations",
        ["child_run_id"],
        unique=True,
    )
    for column in (
        "parent_run_id",
        "root_run_id",
        "team_id",
        "source_agent_id",
        "target_agent_id",
    ):
        op.create_index(
            op.f(f"ix_delegations_{column}"),
            "delegations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "target_agent_id",
        "source_agent_id",
        "team_id",
        "root_run_id",
        "parent_run_id",
        "child_run_id",
    ):
        op.drop_index(op.f(f"ix_delegations_{column}"), table_name="delegations")
    op.drop_table("delegations")
    op.drop_index(op.f("ix_team_members_team_id"), table_name="team_members")
    op.drop_index(op.f("ix_team_members_agent_id"), table_name="team_members")
    op.drop_table("team_members")
    op.drop_index(op.f("ix_teams_coordinator_agent_id"), table_name="teams")
    op.drop_table("teams")
    op.drop_index("uq_runs_one_active_per_session", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_parent_run_id")
        batch_op.drop_constraint("fk_runs_parent_run_id", type_="foreignkey")
        batch_op.drop_column("depth")
        batch_op.drop_column("parent_run_id")
    op.create_index(
        "uq_runs_one_active_per_session",
        "runs",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )
