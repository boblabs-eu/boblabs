"""Bob Manager — AI Orchestrator ORM models."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# ── Orchestrator Settings (singleton) ─────────────


class OrchestratorSettings(Base):
    __tablename__ = "orchestrator_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    orchestrator_model: Mapped[str] = mapped_column(String(255), default="qwen2.5:72b")
    orchestrator_provider: Mapped[str] = mapped_column(String(50), default="ollama")
    orchestrator_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=4)
    artifact_storage_path: Mapped[str] = mapped_column(String(500), default="/data/artifacts")
    log_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── AI Providers ──────────────────────────────────


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cluster I — auto-discovery from agent metrics ticks creates rows
    # with pending_approval=True so an attacker who learned AGENT_SECRET
    # cannot register a provider that immediately serves dispatch
    # traffic. Existing rows were grandfathered to False by migration
    # 0005. Engine resolvers filter on pending_approval=False.
    pending_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── AI Models ─────────────────────────────────────


class AIModel(Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_identifier", name="uq_provider_model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── AI Agents ─────────────────────────────────────


class AIAgent(Base):
    __tablename__ = "ai_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.70"))
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    tools: Mapped[list] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Conversations ─────────────────────────────────


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), default="New Conversation")
    status: Mapped[str] = mapped_column(String(50), default="active")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    tools: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default="[]", default=list
    )
    acl: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"owner":"admin","editors":[],"viewers":[]}',
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Messages ──────────────────────────────────────


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Orchestrator Tasks ────────────────────────────


class OrchestratorTask(Base):
    __tablename__ = "orchestrator_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orchestrator_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(String(100), default="inference")
    priority: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    input_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    gpu_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── GPU Locks ─────────────────────────────────────


class GpuLock(Base):
    __tablename__ = "gpu_locks"
    __table_args__ = (UniqueConstraint("server_id", "gpu_index", name="uq_gpu_lock"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    gpu_index: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orchestrator_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ══════════════════════════════════════════════════
# Lab models
# ══════════════════════════════════════════════════


class CronJob(Base):
    """Reusable CRON job definition — global library."""

    __tablename__ = "cron_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    expression: Mapped[str] = mapped_column(String(100), nullable=False)
    method: Mapped[str] = mapped_column(
        String(30),
        default="orchestrator_inject",
        server_default="orchestrator_inject",
        comment="orchestrator_inject | direct_cmd_exec",
    )
    instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ToolSet(Base):
    """Reusable named collection of tools, available globally."""

    __tablename__ = "tool_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromptTemplate(Base):
    """Reusable prompt template with variable interpolation."""

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(
        String(20),
        default="agent",
        server_default="agent",
        comment="Where to apply: 'agent' or 'orchestrator'",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LibraryAgent(Base):
    """Standalone reusable agent definition — not tied to any lab."""

    __tablename__ = "library_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, default="", server_default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.70"))
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    tool_set_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    share_memory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    callable_agents: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cron_instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    anti_loop_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="created", server_default="created")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Loop strategy
    loop_type: Mapped[str] = mapped_column(
        String(50), default="plan_execute", server_default="plan_execute"
    )
    loop_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    # Orchestrator config
    orchestrator_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    orchestrator_prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    orchestrator_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    orchestrator_temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.70")
    )
    orchestrator_max_tokens: Mapped[int] = mapped_column(Integer, default=4096)

    # Execution limits
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_iteration: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Scheduling
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Context files
    context_files: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Memory sharing override (null = use agent default)
    share_memory_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Strategy prompt override (per-lab, replaces hardcoded prompt)
    strategy_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Auto sweep: orchestrator periodically reviews agent memories
    auto_sweep_memory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Anti-loop: detect repetitive behavior, pause, strip looping messages, resume
    anti_loop_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Public visibility on the anonymous /live page. Defaults to false — labs are
    # private unless the owner (or an admin) explicitly opts in. Independent from
    # the ACL (which gates authenticated owner/editors/viewers access).
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Orchestrator tool support
    orchestrator_tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    orchestrator_tool_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_sets.id", ondelete="SET NULL"), nullable=True
    )
    orchestrator_tool_set_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    # CRON jobs from library
    cron_job_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Tool execution safety limits
    tool_max_calls: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    tool_timeout_sec: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    tool_max_output_kb: Mapped[int] = mapped_column(Integer, default=256, server_default="256")
    tool_container_memory_mb: Mapped[int] = mapped_column(
        Integer, default=512, server_default="512"
    )

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Access control
    acl: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"owner":"admin","editors":[],"viewers":[]}',
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LabAgent(Base):
    __tablename__ = "lab_agents"
    __table_args__ = (UniqueConstraint("lab_id", "name", name="uq_lab_agent_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    library_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("library_agents.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Text, default="", server_default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.70"))
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    tools: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    tool_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_sets.id", ondelete="SET NULL"), nullable=True
    )
    tool_set_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    share_memory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    callable_agents: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cron_instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    anti_loop_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LabTool(Base):
    __tablename__ = "lab_tools"
    __table_args__ = (UniqueConstraint("lab_id", "name", name="uq_lab_tool_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tool_type: Mapped[str] = mapped_column(String(50), default="builtin", server_default="builtin")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    execution_side: Mapped[str] = mapped_column(
        String(10), default="server", server_default="server"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabMessage(Base):
    __tablename__ = "lab_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_agents.id", ondelete="SET NULL"), nullable=True
    )
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    target_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_agents.id", ondelete="SET NULL"), nullable=True
    )
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(20), default="message", server_default="message"
    )

    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabMemory(Base):
    __tablename__ = "lab_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_agents.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(20), default="lab", server_default="lab")
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(20), default="fact", server_default="fact")
    importance: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class LabResource(Base):
    __tablename__ = "lab_resources"
    __table_args__ = (UniqueConstraint("lab_id", "filename", name="uq_lab_resource_file"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    resource_type: Mapped[str] = mapped_column(String(50), default="file", server_default="file")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabScheduleLog(Base):
    __tablename__ = "lab_schedule_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running", server_default="running")
    iterations_run: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ══════════════════════════════════════════════════
# LLM Events (load-balancer activity log)
# ══════════════════════════════════════════════════


class LlmEvent(Base):
    """Tracks every LLM request flowing through the dispatcher.

    event_type: 'queue' | 'dispatch' | 'response' | 'failed'
    caller_type: 'conversation' | 'lab_orchestrator' | 'lab_agent'
    """

    __tablename__ = "llm_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    model_identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    server_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caller_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    caller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lab_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_messages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ToolConfig(Base):
    """Per-tool configuration (SMTP credentials, Twitter API keys, etc.)."""

    __tablename__ = "tool_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_type: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
