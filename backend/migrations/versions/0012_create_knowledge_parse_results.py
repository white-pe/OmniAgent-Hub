"""Create current text parse results for document versions.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 此处字段、约束需要与 ORM 模型保持一致。
    # 迁移负责修改真实数据库，模型负责描述应用使用的数据结构。
    op.create_table(
        "knowledge_document_parse_results",
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("source_format", sa.String(30), nullable=False),
        sa.Column("parser_name", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_count > 0",
            name="ck_knowledge_parse_result_char_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id"),
    )


def downgrade() -> None:
    # 只删除本次迁移创建的派生结果表，源文件版本表继续保留。
    op.drop_table("knowledge_document_parse_results")