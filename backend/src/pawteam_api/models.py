"""SQLAlchemy metadata and stage-zero bootstrap table."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SystemMetadata(Base):
    """Small table proving migrations and ORM metadata are wired correctly."""

    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Provider(Base):
    """An OpenAI-compatible endpoint and its non-secret configuration."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False, default="openai_compatible"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_ref: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    models: Mapped[list["ProviderModel"]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProviderModel.created_at",
    )


class ProviderModel(Base):
    """A concrete model exposed by one Provider."""

    __tablename__ = "provider_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_name", name="uq_provider_model_name"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    capabilities_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    provider: Mapped[Provider] = relationship(back_populates="models")


class Agent(Base):
    """Agent metadata; prompt files live in its isolated Workspace."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    workspace_path: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(
        ForeignKey("provider_models.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_coordinator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AgentBlueprintDraft(Base):
    """Reviewable LLM output; applying it is a separate explicit action."""

    __tablename__ = "agent_blueprint_drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    request_text: Mapped[str] = mapped_column(String(4000), nullable=False)
    source_provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_model_id: Mapped[str] = mapped_column(
        ForeignKey("provider_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blueprint_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    applied_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChatSession(Base):
    """A durable console conversation bound to exactly one Agent."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="console")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRun(Base):
    """One model execution and its durable lifecycle state."""

    __tablename__ = "runs"
    __table_args__ = (
        Index(
            "uq_runs_one_active_per_session",
            "session_id",
            unique=True,
            sqlite_where=text(
                "parent_run_id IS NULL "
                "AND status IN ('queued', 'running', 'cancelling')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(
        ForeignKey("provider_models.id", ondelete="RESTRICT"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    output_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Message(Base):
    """Ordered durable chat content; Run state remains in the runs table."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_message_sequence"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="final")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunEvent(Base):
    """Replayable SSE event emitted by one Run."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    data_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Skill(Base):
    """Agent-specific strategy metadata backed by a Workspace SKILL.md."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("agent_id", "name", name="uq_agent_skill_name"),
        UniqueConstraint("agent_id", "path", name="uq_agent_skill_path"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_scope_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["console"]
    )
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AgentTool(Base):
    """Per-Agent enablement for one server-owned Tool definition."""

    __tablename__ = "agent_tools"
    __table_args__ = (
        UniqueConstraint("agent_id", "tool_name", name="uq_agent_tool_name"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ToolCall(Base):
    """Auditable request, validation, execution, and result for one Tool call."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "provider_call_id", name="uq_run_provider_call"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Team(Base):
    """A coordinator-owned allowlist of Agents that may receive delegated work."""

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    coordinator_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TeamMember(Base):
    """One Agent's explicit role inside a Team."""

    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "agent_id", name="uq_team_member_agent"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Delegation(Base):
    """A durable parent-to-child Agent handoff and its final result."""

    __tablename__ = "delegations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    parent_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    root_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    result_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Channel(Base):
    """One external message adapter bound to exactly one Agent."""

    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="wecom")
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    secret_ref: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExternalConversation(Base):
    """Stable mapping from an external conversation to an internal ChatSession."""

    __tablename__ = "external_conversations"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "external_conversation_id",
            name="uq_channel_external_conversation",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_conversation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    chat_session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChannelMessage(Base):
    """Durable inbound receipt or leased outbound delivery item."""

    __tablename__ = "channel_messages"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "direction",
            "external_message_id",
            name="uq_channel_direction_external_message",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_conversation_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    chat_session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeBase(Base):
    """Managed knowledge collection; Agent access uses explicit bindings."""
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class AgentKnowledgeBinding(Base):
    """Explicit permission for one Agent to access one knowledge base."""

    __tablename__ = "agent_knowledge_bindings"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocument(Base):
    """Logical document stored in one managed knowledge base."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_knowledge_base_id", "knowledge_base_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeDocumentVersion(Base):
    """Immutable source-file metadata for one document version."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_knowledge_document_version_number",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_knowledge_document_version_positive",
        ),
        CheckConstraint(
            "size_bytes >= 0",
            name="ck_knowledge_document_version_size_nonnegative",
        ),
        Index("ix_knowledge_document_versions_document_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeDocumentParseResult(Base):
    """一个源文件版本当前采用的文本解析结果。"""

    __tablename__ = "knowledge_document_parse_results"
    __table_args__ = (
        # 非空文本是成功解析的最低条件。
        # char_count 与实际文本长度的一致性，由后续 Service 统一保证。
        CheckConstraint(
            "char_count > 0",
            name="ck_knowledge_parse_result_char_count_positive",
        ),
    )

    # 直接用源文件版本 ID 作为主键，同时也是外键：
    # 一个版本最多保存一份当前解析结果，不能重复插入。
    # 删除源文件版本时，关联解析结果一起删除。
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # 保存规范化后的文本，后续切块从这里读取，
    # 不必每次重新打开原文件、解码、规范化换行。
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # 这里记录字符数，不是 UTF-8 字节数。
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 对应解析器返回的 txt 或 markdown。
    # 使用字符串方便后续扩展其他格式。
    source_format: Mapped[str] = mapped_column(String(30), nullable=False)

    # 记录产生这份文本的处理规则，方便诊断和后续重新解析。
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(30), nullable=False)

    # 表示这份解析结果生成的时间。
    # 将来重新解析时，需要明确替换结果并更新这一时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeChunkSet(Base):
    """针对一份解析文本和一组配置生成的切块批次。"""

    __tablename__ = "knowledge_chunk_sets"
    __table_args__ = (
        # 相同源文本、算法版本和参数只保存一份批次。
        # 不同参数允许并存，方便后续做检索效果对比。
        UniqueConstraint(
            "version_id",
            "source_text_sha256",
            "splitter_name",
            "splitter_version",
            "chunk_size",
            "chunk_overlap",
            name="uq_knowledge_chunk_set_config",
        ),
        CheckConstraint(
            "chunk_size > 0",
            name="ck_knowledge_chunk_set_size_positive",
        ),
        CheckConstraint(
            "chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_knowledge_chunk_set_overlap_valid",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )

    # 直接依赖解析结果，避免为尚未解析的版本创建切块产物。
    # 删除解析结果时，对应批次及其片段也应被删除。
    version_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_document_parse_results.version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # 这是“规范化后解析文本”的摘要，不是上传原文件的摘要。
    # 后续 Service 会对 parse_result.text.encode("utf-8") 计算。
    source_text_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )

    # 记录本项目定义的算法及规则版本。
    # 将来分隔符、清洗规则或依赖行为变化，需要升级 splitter_version。
    splitter_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    splitter_version: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    # 本阶段明确按 Python 字符数量计量，不是字节数或模型 token 数。
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # 表示期望的重叠上限。
    # 后续采用结构分割时，相邻片段不一定恰好重叠这么多字符。
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeChunk(Base):
    """一个切块批次中的文本片段及其原文位置。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "chunk_set_id",
            "chunk_index",
            name="uq_knowledge_chunk_set_index",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunk_index_nonnegative",
        ),
        CheckConstraint(
            "start_char >= 0 AND end_char > start_char",
            name="ck_knowledge_chunk_offsets_valid",
        ),
        CheckConstraint(
            "char_count = end_char - start_char",
            name="ck_knowledge_chunk_char_count_matches_span",
        ),
    )

    # 使用独立 UUID，方便未来向量记录和引用结果关联具体片段。
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    chunk_set_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_chunk_sets.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 从 0 开始编号，查询时必须显式按该字段排序。
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # 使用左闭右开区间，对应解析文本：
    # parse_result.text[start_char:end_char] == chunk.text
    # 这是规范化文本的位置，不是原始文件的字节位置。
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeEmbeddingProfile(Base):
    """描述一组生成文档和查询向量所使用的配置。"""

    __tablename__ = "knowledge_embedding_profiles"
    __table_args__ = (
        # 完全相同的配置只保存一份。
        # base_url 保存快照，不能仅依赖未来可能修改的 Provider 地址。
        UniqueConstraint(
            "provider_id",
            "base_url",
            "model_name",
            "model_revision",
            "dimensions",
            "send_dimensions",
            "input_policy_version",
            name="uq_knowledge_embedding_profile_config",
        ),
        CheckConstraint(
            "dimensions > 0",
            name="ck_knowledge_embedding_dimensions_positive",
        ),
        Index(
            "ix_knowledge_embedding_profiles_provider_id",
            "provider_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # 配置引用的 Provider 不允许直接删除。
    # 密钥仍由 Provider + SecretStore 管理，不复制到本表。
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # 保存生成向量时使用的地址；后续执行时要检查配置是否发生漂移。
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # 这是平台维护的版本标签，不代表上游已经固定模型权重。
    model_revision: Mapped[str] = mapped_column(String(100), nullable=False)

    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    send_dimensions: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # raw-v1 表示当前直接使用片段正文。
    # 将来添加指令前缀、清洗等规则，需要建立新策略版本和新配置。
    input_policy_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeChunkEmbedding(Base):
    """一个片段在指定 Embedding 配置下对应的一份向量。"""

    __tablename__ = "knowledge_chunk_embeddings"
    __table_args__ = (
        # 联合主键已支持按 profile_id 查询；
        # 另加 chunk_id 索引，服务片段关联查询和删除清理。
        Index(
            "ix_knowledge_chunk_embeddings_chunk_id",
            "chunk_id",
        ),
    )

    # 联合主键保证：
    # 同一配置 + 同一片段，最多保存一份向量。
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_embedding_profiles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # 当前先保存原始数值，维度从 profile 读取，不重复维护。
    # 写入前必须由后续持久化 Service 使用 EmbeddingBatch 校验。
    vector: Mapped[list[float]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgePublication(Base):
    """每个文档只发布一个批次，切换配置或版本时原子替换指针。"""

    __tablename__ = "knowledge_publications"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_set_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_chunk_sets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_embedding_profiles.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class KnowledgeIngestionJob(Base):
    """单机任务队列；进程重启后失败任务可人工重试，不静默丢失。"""

    __tablename__ = "knowledge_ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_knowledge_job_status",
        ),
        Index("ix_knowledge_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_embedding_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    # 相同文档同时只处理一个任务；终态置空，允许后续再次提交。
    active_key: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_set_id: Mapped[str | None] = mapped_column(String(36))
    rebuild: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class KnowledgeQueryLog(Base):
    """只记录问题摘要、关联 ID 与耗时，不持久化原始问题和模型密钥。"""

    __tablename__ = "knowledge_query_logs"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class KnowledgeQueryHistory(Base):
    """管理员可回看的逐次查询快照；与不保存正文的审计摘要分表。"""

    __tablename__ = "knowledge_query_history"
    request_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_query_logs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class KnowledgeVectorIndex(Base):
    """一个切块批次在指定 Embedding Profile 下的索引状态。"""

    __tablename__ = "knowledge_vector_indexes"
    __table_args__ = (
        # 仅允许服务端约定的状态值，避免状态拼写不一致。
        CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'failed')",
            name="ck_knowledge_vector_index_status",
        ),
        CheckConstraint(
            "expected_points >= 0 AND indexed_points >= 0",
            name="ck_knowledge_vector_index_points_nonnegative",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_knowledge_vector_index_attempts_nonnegative",
        ),
        CheckConstraint(
            "indexed_points <= expected_points",
            name="ck_knowledge_vector_index_points_within_expected",
        ),
        Index(
            "ix_knowledge_vector_indexes_status_lease",
            "status",
            "lease_until",
        ),
    )

    # 一个 Profile + 一个切块批次最多对应一条索引任务状态。
    profile_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_embedding_profiles.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    chunk_set_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_chunk_sets.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    # pending：等待处理；indexing：正在处理；
    # indexed：所有点已写入；failed：上次处理失败，可重试。
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    # expected_points 是关系数据库中应写入的片段数；
    # indexed_points 记录服务确认写入的数量。
    expected_points: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    indexed_points: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # 每次开始处理时累加，可用于管理界面展示重试次数。
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # 只保存清理后的错误摘要，不保存向量、文档正文或密钥。
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 后续 worker 接手时用于识别超时任务，避免任务永久停在 indexing。
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
