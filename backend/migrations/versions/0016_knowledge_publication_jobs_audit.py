"""Publish retrieval sources and persist ingestion jobs and query audits."""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_publications",
        sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chunk_set_id", sa.String(36), sa.ForeignKey("knowledge_chunk_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("knowledge_embedding_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_publications_chunk_set_id", "knowledge_publications", ["chunk_set_id"])
    op.create_index("ix_knowledge_publications_profile_id", "knowledge_publications", ["profile_id"])
    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("knowledge_embedding_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active_key", sa.String(36), unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("chunk_set_id", sa.String(36)),
        sa.Column("rebuild", sa.Boolean(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_knowledge_job_status"),
    )
    op.create_index("ix_knowledge_jobs_status_created", "knowledge_ingestion_jobs", ["status", "created_at"])
    op.create_table(
        "knowledge_query_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_query_logs_created_at", "knowledge_query_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("knowledge_query_logs")
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_table("knowledge_publications")
