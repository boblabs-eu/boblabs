"""Bob Manager — AI Orchestrator Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# O05 — Single source of truth for the loop_type column. Mirrored by the
# DB CHECK constraint added in migration 0010 and by the strategy registry
# in ``app.services.loop_strategies.__init__``. If you add a new strategy:
# (1) register it there, (2) widen this Literal, (3) widen the CHECK.
LoopTypeStr = Literal[
    "plan_execute",
    "critique_refine",
    "round_robin",
    "debate",
    "map_reduce",
    "parallel_broadcast",
    "tree_of_thought",
    "react",
    "supervisor",
    "solo_agent",
]


# ── Settings ──────────────────────────────────────


class OrchestratorSettingsResponse(BaseModel):
    orchestrator_model: str
    orchestrator_provider: str
    orchestrator_server_id: UUID | None = None
    max_concurrent_tasks: int
    artifact_storage_path: str
    log_retention_days: int
    updated_at: datetime

    class Config:
        from_attributes = True


class OrchestratorSettingsUpdate(BaseModel):
    orchestrator_model: str | None = None
    orchestrator_provider: str | None = None
    orchestrator_server_id: UUID | None = None
    max_concurrent_tasks: int | None = None
    artifact_storage_path: str | None = None
    log_retention_days: int | None = None


# ── AI Providers ──────────────────────────────────


class AIProviderCreate(BaseModel):
    name: str
    provider_type: str  # ollama | huggingface | openai
    base_url: str
    api_key: str | None = None
    server_id: UUID | None = None
    is_active: bool = True


class AIProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    server_id: UUID | None = None
    is_active: bool | None = None


class AIProviderResponse(BaseModel):
    id: UUID
    name: str
    provider_type: str
    base_url: str
    api_key: str | None = None
    server_id: UUID | None = None
    server_name: str | None = None
    is_active: bool
    # Cluster I — surface so the admin UI can render an "Approve" button
    # for auto-discovered rows.
    pending_approval: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── AI Models ─────────────────────────────────────


class AIModelResponse(BaseModel):
    id: UUID
    name: str
    provider_id: UUID
    model_identifier: str
    capabilities: dict
    parameters: dict
    is_available: bool
    last_seen_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── AI Agents ─────────────────────────────────────


class AIAgentCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    model_id: UUID | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list = []
    is_active: bool = True


class AIAgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_id: UUID | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list | None = None
    is_active: bool | None = None


class AIAgentResponse(BaseModel):
    id: UUID
    name: str
    description: str
    system_prompt: str
    model_id: UUID | None = None
    temperature: float
    max_tokens: int
    tools: list
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Conversations ─────────────────────────────────


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    agent_id: UUID | None = None
    tools: list[str] | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    agent_id: UUID | None = None
    tools: list[str] | None = None


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    status: str
    agent_id: UUID | None = None
    tools: list[str] | None = None
    created_at: datetime
    updated_at: datetime
    last_message: str | None = None  # populated in service layer
    message_count: int = 0

    class Config:
        from_attributes = True


# ── Messages ──────────────────────────────────────


class MessageCreate(BaseModel):
    content: str
    model: str | None = None
    images: list[str] | None = None  # base64 or data URI strings
    context_mode: str | None = None  # 'full' | 'minimal' (default: minimal)
    agent_id: UUID | None = None  # override conversation default agent
    tools: list[str] | None = None  # ad-hoc tools for this message


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    agent_id: UUID | None = None
    agent_name: str | None = None
    model_used: str | None = None
    provider_used: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None
    extra: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


# ── Tasks ─────────────────────────────────────────


class TaskResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    parent_task_id: UUID | None = None
    agent_id: UUID | None = None
    task_type: str
    priority: int
    status: str
    input_data: dict
    output_data: dict | None = None
    server_id: UUID | None = None
    gpu_index: int | None = None
    error: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


# ── Activity Feed ─────────────────────────────────


class ActivityItem(BaseModel):
    """Combined view of messages + tasks for the activity feed."""

    id: UUID
    type: str  # message | task
    conversation_id: UUID
    timestamp: datetime
    # Message fields
    role: str | None = None
    content: str | None = None
    agent_name: str | None = None
    # Task fields
    task_type: str | None = None
    task_status: str | None = None
    task_error: str | None = None


# ══════════════════════════════════════════════════
# Lab schemas
# ══════════════════════════════════════════════════


class LabCreate(BaseModel):
    name: str
    description: str = ""
    loop_type: LoopTypeStr = "plan_execute"
    loop_config: dict = {}
    orchestrator_model_id: UUID | None = None
    orchestrator_prompt: str = ""
    orchestrator_prompt_template_id: UUID | None = None
    orchestrator_temperature: float = 0.7
    orchestrator_max_tokens: int = 4096
    max_iterations: int | None = None
    max_duration_sec: int | None = None
    cron_expression: str | None = None
    context_files: list[dict] = []
    share_memory_override: bool | None = None
    strategy_prompt_override: str | None = None
    orchestrator_tools: list[str] = []
    orchestrator_tool_set_id: UUID | None = None
    orchestrator_tool_set_ids: list[str] = []
    auto_sweep_memory: bool = False
    anti_loop_enabled: bool = False
    cron_job_ids: list[str] = []
    tool_max_calls: int = 10
    tool_timeout_sec: int = 30
    tool_max_output_kb: int = 256
    tool_container_memory_mb: int = 512


class LabUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    loop_type: LoopTypeStr | None = None
    loop_config: dict | None = None
    orchestrator_model_id: UUID | None = None
    orchestrator_prompt: str | None = None
    orchestrator_prompt_template_id: UUID | None = None
    orchestrator_temperature: float | None = None
    orchestrator_max_tokens: int | None = None
    max_iterations: int | None = None
    max_duration_sec: int | None = None
    cron_expression: str | None = None
    context_files: list[dict] | None = None
    share_memory_override: bool | None = None
    strategy_prompt_override: str | None = None
    orchestrator_tools: list[str] | None = None
    orchestrator_tool_set_id: UUID | None = None
    orchestrator_tool_set_ids: list[str] | None = None
    auto_sweep_memory: bool | None = None
    anti_loop_enabled: bool | None = None
    cron_job_ids: list[str] | None = None
    tool_max_calls: int | None = None
    tool_timeout_sec: int | None = None
    tool_max_output_kb: int | None = None
    tool_container_memory_mb: int | None = None


class LabResponse(BaseModel):
    id: UUID
    name: str
    description: str
    status: str
    failure_reason: str | None = None
    loop_type: str
    loop_config: dict
    orchestrator_model_id: UUID | None
    orchestrator_prompt: str
    orchestrator_prompt_template_id: UUID | None = None
    orchestrator_temperature: float
    orchestrator_max_tokens: int
    max_iterations: int | None
    max_duration_sec: int | None
    current_iteration: int
    cron_expression: str | None
    next_run_at: datetime | None
    context_files: list[dict]
    share_memory_override: bool | None
    orchestrator_tools: list
    orchestrator_tool_set_id: UUID | None
    orchestrator_tool_set_ids: list = []
    strategy_prompt_override: str | None = None
    auto_sweep_memory: bool = False
    anti_loop_enabled: bool = False
    cron_job_ids: list = []
    tool_max_calls: int
    tool_timeout_sec: int
    tool_max_output_kb: int
    tool_container_memory_mb: int
    started_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Populated by service
    agent_count: int = 0
    message_count: int = 0
    acl: dict = {}

    class Config:
        from_attributes = True


# ── Lab Agent ─────────────────────────────────────


class LabAgentCreate(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    prompt_template_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_set_id: UUID | None = None
    tool_set_ids: list[str] = []
    is_active: bool = True
    sort_order: int = 0
    share_memory: bool = False
    callable_agents: list[str] = []
    cron_expression: str | None = None
    cron_instruction: str = ""
    anti_loop_enabled: bool = False
    library_agent_id: UUID | None = None


class LabAgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    prompt_template_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[str] | None = None
    tool_set_id: UUID | None = None
    tool_set_ids: list[str] | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    share_memory: bool | None = None
    callable_agents: list[str] | None = None
    cron_expression: str | None = None
    cron_instruction: str | None = None
    anti_loop_enabled: bool | None = None


class LabAgentResponse(BaseModel):
    id: UUID
    lab_id: UUID
    name: str
    role: str
    system_prompt: str
    prompt_template_id: UUID | None = None
    model_id: UUID | None
    temperature: float
    max_tokens: int
    tools: list
    tool_set_id: UUID | None
    tool_set_ids: list = []
    is_active: bool
    sort_order: int
    share_memory: bool
    callable_agents: list
    cron_expression: str | None
    cron_instruction: str
    anti_loop_enabled: bool = False
    library_agent_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Library Agent ─────────────────────────────────


class LibraryAgentCreate(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    prompt_template_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_set_ids: list[str] = []
    share_memory: bool = False
    callable_agents: list[str] = []
    cron_expression: str | None = None
    cron_instruction: str = ""
    anti_loop_enabled: bool = False


class LibraryAgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    prompt_template_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[str] | None = None
    tool_set_ids: list[str] | None = None
    share_memory: bool | None = None
    callable_agents: list[str] | None = None
    cron_expression: str | None = None
    cron_instruction: str | None = None
    anti_loop_enabled: bool | None = None


class LibraryAgentResponse(BaseModel):
    id: UUID
    name: str
    role: str
    system_prompt: str
    prompt_template_id: UUID | None = None
    model_id: UUID | None
    temperature: float
    max_tokens: int
    tools: list
    tool_set_ids: list = []
    share_memory: bool
    callable_agents: list
    cron_expression: str | None
    cron_instruction: str
    anti_loop_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── CRON Job ──────────────────────────────────────


class CronJobCreate(BaseModel):
    name: str
    description: str = ""
    expression: str
    method: str = "orchestrator_inject"  # orchestrator_inject | direct_cmd_exec
    instruction: str = ""


class CronJobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    expression: str | None = None
    method: str | None = None
    instruction: str | None = None


class CronJobResponse(BaseModel):
    id: UUID
    name: str
    description: str
    expression: str
    method: str
    instruction: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Tool Set ──────────────────────────────────────


class ToolSetCreate(BaseModel):
    name: str
    description: str = ""
    tools: list[str] = []


class ToolSetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tools: list[str] | None = None


class ToolSetResponse(BaseModel):
    id: UUID
    name: str
    description: str
    tools: list
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Prompt Template ───────────────────────────────


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    content: str
    target: str = "agent"  # agent | orchestrator


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    target: str | None = None


class PromptTemplateResponse(BaseModel):
    id: UUID
    name: str
    description: str
    content: str
    target: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Lab Tool ──────────────────────────────────────


class LabToolCreate(BaseModel):
    name: str
    description: str = ""
    tool_type: str = "builtin"
    config: dict = {}
    execution_side: str = "server"
    is_enabled: bool = True


class LabToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tool_type: str | None = None
    config: dict | None = None
    execution_side: str | None = None
    is_enabled: bool | None = None


class LabToolResponse(BaseModel):
    id: UUID
    lab_id: UUID
    name: str
    description: str
    tool_type: str
    config: dict
    execution_side: str
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Lab Message ───────────────────────────────────


class LabMessageResponse(BaseModel):
    id: UUID
    lab_id: UUID
    iteration: int
    sender_type: str
    sender_agent_id: UUID | None
    sender_name: str | None
    target_agent_id: UUID | None
    target_name: str | None
    content: str
    message_type: str
    model_used: str | None
    provider_used: str | None
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int | None
    tool_name: str | None
    tool_input: dict | None
    tool_output: dict | None
    extra: dict
    created_at: datetime

    class Config:
        from_attributes = True


# ── Lab Memory ────────────────────────────────────


class LabMemoryResponse(BaseModel):
    id: UUID
    lab_id: UUID
    agent_id: UUID | None
    scope: str
    key: str
    content: str
    memory_type: str
    importance: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    is_hidden: bool = False

    class Config:
        from_attributes = True


# ── Lab Inject ────────────────────────────────────


class LabInject(BaseModel):
    content: str


# ── Lab Resource ──────────────────────────────────


class LabResourceResponse(BaseModel):
    id: UUID
    lab_id: UUID
    filename: str
    original_name: str
    content_type: str
    size_bytes: int
    resource_type: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Lab Blueprint (JSON Import/Export) ────────────


class LabBlueprintAgent(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    prompt_template: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_sets: list[str] = []
    is_active: bool = True
    sort_order: int = 0
    share_memory: bool = False
    callable_agents: list[str] = []
    cron_expression: str | None = None
    cron_instruction: str = ""
    anti_loop_enabled: bool = False

    class Config:
        extra = "allow"


class LabBlueprintOrchestrator(BaseModel):
    model: str | None = None
    prompt: str = ""
    prompt_template: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_sets: list[str] = []

    class Config:
        extra = "allow"


class LabBlueprintSettings(BaseModel):
    max_iterations: int | None = None
    max_duration_sec: int | None = None
    cron_expression: str | None = None
    tool_max_calls: int = 10
    tool_timeout_sec: int = 30
    tool_max_output_kb: int = 256
    tool_container_memory_mb: int = 512
    share_memory_override: bool | None = None
    auto_sweep_memory: bool = False

    class Config:
        extra = "allow"


class RagAccessRef(BaseModel):
    collection_name: str = Field(min_length=1, max_length=255)
    can_read: bool = True
    can_write: bool = False

    class Config:
        extra = "allow"


class LabBlueprintLab(BaseModel):
    name: str
    description: str = ""
    loop_type: LoopTypeStr = "plan_execute"
    loop_config: dict = {}
    strategy_prompt_override: str | None = None
    context_files: list[dict] = []
    orchestrator: LabBlueprintOrchestrator = LabBlueprintOrchestrator()
    settings: LabBlueprintSettings = LabBlueprintSettings()
    agents: list[LabBlueprintAgent] = []
    rag_access: list[RagAccessRef] = []
    anti_loop_enabled: bool = False

    class Config:
        extra = "allow"


class LabBlueprint(BaseModel):
    version: int = 1
    lab: LabBlueprintLab

    class Config:
        extra = "allow"


# ── Agent Blueprint (consumer-app standalone agents) ────────────────────────
#
# Mirror of LabBlueprint for the single-agent case. A consumer app POSTs one
# of these to /internal/apps/import_agent to register a callable agent in the
# library_agents namespace ``app__<app_id>__<name>``. It can then be invoked
# via /run_agent (sync wrapper around an ephemeral single-agent lab) or fired
# by the scheduler if ``cron_expression`` is set.


class AgentBlueprintAgent(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    description: str = ""
    prompt_template: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_sets: list[str] = []
    share_memory: bool = False
    callable_agents: list[str] = []
    cron_expression: str | None = None
    cron_instruction: str = ""
    anti_loop_enabled: bool = False
    rag_access: list[RagAccessRef] = []

    class Config:
        extra = "allow"


class AgentBlueprint(BaseModel):
    version: int = 1
    agent: AgentBlueprintAgent

    class Config:
        extra = "allow"


# ── Tool Config schemas ─────────────────────────────


class ToolConfigCreate(BaseModel):
    tool_type: str
    config: dict = {}


class ToolConfigUpdate(BaseModel):
    config: dict


class ToolConfigResponse(BaseModel):
    id: str
    tool_type: str
    config: dict
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


# ── Public Live schemas (sanitized, no secrets) ─────


class LiveLabAgent(BaseModel):
    id: UUID
    name: str
    model_id: UUID | None = None
    model_name: str | None = None
    temperature: float = 0.7
    tools_count: int = 0
    is_active: bool = True


class LiveLabSummary(BaseModel):
    id: UUID
    name: str
    description: str = ""
    status: str = "idle"
    loop_type: str = "plan_execute"
    current_iteration: int = 0
    max_iterations: int = 10
    agent_count: int = 0
    updated_at: datetime | None = None


class LiveLabDetail(LiveLabSummary):
    agents: list[LiveLabAgent] = []
    orchestrator_model_id: UUID | None = None
    orchestrator_model_name: str | None = None


class LiveLabMessage(BaseModel):
    id: UUID
    iteration: int = 0
    sender_type: str = ""
    sender_name: str | None = None
    content: str = ""
    message_type: str = ""
    model_used: str | None = None
    provider_used: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    tool_name: str | None = None
    created_at: datetime


class LiveLabResource(BaseModel):
    id: UUID
    filename: str
    original_name: str
    content_type: str = ""
    size_bytes: int = 0
    resource_type: str = ""

    class Config:
        from_attributes = True


class LiveServer(BaseModel):
    id: UUID
    name: str
    host: str = ""
    status: str = "offline"
    gpu_info: dict | None = None
    os_info: dict | None = None
    last_heartbeat: datetime | None = None

    class Config:
        from_attributes = True


class LiveProvider(BaseModel):
    id: UUID
    name: str
    provider_type: str = ""
    is_active: bool = True
    server_id: UUID | None = None
    server_name: str | None = None

    class Config:
        from_attributes = True
