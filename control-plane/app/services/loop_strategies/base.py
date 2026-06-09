"""Bob Manager — Loop strategy abstraction.

The loop strategy is the pluggable brain of a Lab. It decides WHAT to do,
while the Lab Runner handles HOW to execute it.

Users can swap strategies by changing `lab.loop_type`.
"""

from __future__ import annotations

import base64
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent, LabMemory, LabMessage, LabResource

logger = logging.getLogger(__name__)

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

# R13 — cap multi-round strategies' accumulated TaskResult buffer. The four
# debate/round_robin/supervisor/tree_of_thought strategies each slice a
# trailing window (≤30 results) into the system prompt, so anything beyond
# this cap is dead memory that grows for the lifetime of a long-running lab.
MAX_ACCUMULATED_RESULTS = 200


def trim_results(buf: list, max_len: int = MAX_ACCUMULATED_RESULTS) -> list:
    """Trim ``buf`` in place to its last ``max_len`` items and return it."""
    if len(buf) > max_len:
        del buf[: len(buf) - max_len]
    return buf


# ── Actions returned by strategies ────────────────


@dataclass
class PlanAction:
    """Dispatch a set of tasks to agents."""

    tasks: list[TaskItem]


@dataclass
class TaskItem:
    agent_name: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SynthesizeAction:
    """The goal is achieved — produce final summary."""

    summary: str


@dataclass
class PauseAction:
    """Strategy requests a pause."""

    reason: str


LoopAction = PlanAction | SynthesizeAction | PauseAction


# ── Read-only context snapshot ────────────────────


@dataclass
class LoopContext:
    """Snapshot of Lab state passed to the strategy each step."""

    lab: Lab
    agents: list[LabAgent]
    iteration: int
    elapsed_sec: float
    messages: list[LabMessage]
    lab_memories: list[LabMemory]
    user_injections: list[str]
    resources: list[LabResource] = field(default_factory=list)
    orch_tool_names: list[str] = field(default_factory=list)


# ── Task result ───────────────────────────────────


@dataclass
class TaskResult:
    agent_name: str
    instruction: str
    response: str
    model_used: str | None = None
    provider_used: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    error: str | None = None


# ── Abstract strategy ─────────────────────────────


class LoopStrategy(ABC):
    """Abstract base for all Lab loop strategies.

    A strategy controls HOW the orchestrator coordinates agents.
    The Lab Runner delegates all decision-making to the strategy.
    """

    @abstractmethod
    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        """Called once when the lab starts or resumes."""

    @abstractmethod
    async def next_step(self, context: LoopContext) -> LoopAction:
        """Given current context, decide what to do next."""

    @abstractmethod
    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        """Called when agent results come back. Update internal state."""

    @abstractmethod
    async def on_inject(self, context: LoopContext, message: str) -> None:
        """Called when user injects a message mid-run."""


# ── Resource helpers for strategies ───────────────


def inject_memory_index(system: str, memories: list, max_entries: int = 30) -> str:
    """Inject Level-0 memory index: key + importance + short preview.

    Agents use memory_search(query) to load full content (Level-1).
    """
    # Filter out hidden memories
    visible = [m for m in memories if not getattr(m, "is_hidden", False)]
    if not visible:
        return system

    from datetime import datetime, timezone

    system += "\n\n<memory_index>\n"
    for mem in visible[:max_entries]:
        preview = (mem.content or "")[:80].replace("\n", " ")
        if len(mem.content or "") > 80:
            preview += "…"
        # Compute age
        age = ""
        if hasattr(mem, "updated_at") and mem.updated_at:
            try:
                now = datetime.now(timezone.utc)
                delta = (
                    now - mem.updated_at.replace(tzinfo=timezone.utc)
                    if mem.updated_at.tzinfo is None
                    else now - mem.updated_at
                )
                secs = int(delta.total_seconds())
                if secs < 60:
                    age = f"{secs}s ago"
                elif secs < 3600:
                    age = f"{secs // 60}m ago"
                elif secs < 86400:
                    age = f"{secs // 3600}h ago"
                else:
                    age = f"{secs // 86400}d ago"
            except Exception:
                age = ""
        imp = f"imp={mem.importance}" if hasattr(mem, "importance") and mem.importance else ""
        parts = [f"[{mem.key}]", imp, age, preview]
        system += "- " + " ".join(p for p in parts if p) + "\n"
    system += "</memory_index>\n"
    system += "💡 Use memory_search(query) to load full content of any memory.\n"
    return system


def list_output_files(lab_id) -> list[str]:
    """Return list of output file paths for a lab (relative to output/)."""
    output_dir = LAB_RESOURCES_ROOT / str(lab_id) / "output"
    if not output_dir.is_dir():
        return []
    files = []
    for f in sorted(output_dir.rglob("*")):
        if f.is_file() and not f.name.startswith("_exec_tmp"):
            try:
                rel = f.relative_to(output_dir)
                size = f.stat().st_size
                files.append(f"output/{rel} ({size:,} bytes)")
            except Exception:
                pass
    return files


def inject_output_files(system: str, lab_id) -> str:
    """Append output file listing to system prompt."""
    files = list_output_files(lab_id)
    if files:
        system += "\n\n<output_files>\n"
        system += "\n".join(files)
        system += "\n</output_files>\n"
    return system


def format_agents(agents: list) -> str:
    """Standard agent descriptions formatting used by all strategies."""
    lines = []
    for a in agents:
        tools_str = ", ".join(a.tools) if a.tools else "none"
        capabilities = []
        if a.tools:
            if "file_write" in a.tools:
                capabilities.append("can write files")
            if "file_read" in a.tools:
                capabilities.append("can read files")
            if "python_exec" in a.tools:
                capabilities.append("can run Python")
            if "shell_exec" in a.tools:
                capabilities.append("can run shell commands")
            if "web_search" in a.tools or "web_extract" in a.tools:
                capabilities.append("can access web")
            if "call_agent" in a.tools:
                capabilities.append("can call other agents")
        cap_str = f" — {', '.join(capabilities)}" if capabilities else ""
        lines.append(f"- **{a.name}** ({a.role}): Tools: [{tools_str}]{cap_str}")
    return "\n".join(lines)


def build_strategy_system(
    base_prompt: str,
    context: "LoopContext",
    *,
    agent_descriptions: str | None = None,
) -> str:
    """Build the full system prompt: base + custom prompt + context files + memory + resources + output files.

    Shared by ALL strategies to avoid duplication.
    """
    # Use strategy prompt override if the user has customized it for this lab
    override = getattr(context.lab, "strategy_prompt_override", None)
    if override:
        # The override replaces the default strategy prompt
        # Apply the same {lab_name} and {agent_descriptions} placeholders
        try:
            agent_descs = format_agents(context.agents)
            system = override.format(lab_name=context.lab.name, agent_descriptions=agent_descs)
        except (KeyError, IndexError):
            system = override  # fallback: use as-is
    else:
        system = base_prompt

    # Dynamic tools policy: replace the static "CRITICAL" block based on orchestrator tools
    _STATIC_TOOLS_BLOCK = (
        "## CRITICAL: You cannot act — only delegate\n"
        "You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.\n"
        'The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.\n'
        "NEVER say you will do something and then set done=true without dispatching a task for it.\n"
    )
    if context.orch_tool_names:
        from app.services.tool_executor import format_tool_descriptions

        orch_tools_desc = format_tool_descriptions(context.orch_tool_names)
        has_agents = bool(context.agents)
        if has_agents:
            replacement = (
                "## Your Tools\n"
                "You have the following tools available and can use them DIRECTLY:\n"
                f"{orch_tools_desc}\n"
                'You can ALSO delegate tasks to agents via the "tasks" array.\n'
                "Use your own tools for quick actions. Delegate complex multi-step work to agents.\n"
            )
        else:
            replacement = (
                "## Your Tools\n"
                "You have the following tools available and MUST use them to accomplish tasks:\n"
                f"{orch_tools_desc}\n"
                "Use your tools directly to get work done. No agents are configured.\n"
            )
        system = system.replace(_STATIC_TOOLS_BLOCK, replacement)

    # Custom orchestrator prompt
    if context.lab.orchestrator_prompt:
        system += f"\n## Additional Instructions\n{context.lab.orchestrator_prompt}\n"

    # Context files
    if context.lab.context_files:
        system += "\n<context_files>\n"
        for cf in context.lab.context_files:
            system += f"--- {cf.get('name', 'unnamed')} ---\n{cf.get('content', '')}\n\n"
        system += "</context_files>\n"

    # Tiered memory (Level 0 — index only)
    system = inject_memory_index(system, context.lab_memories)

    # Auto sweep instruction
    if getattr(context.lab, "auto_sweep_memory", False):
        system += (
            "\n**Memory Sweep**: You have auto-sweep enabled. Periodically use "
            "handle_memory(agent_name, action='list') to review each agent's memories, "
            "then handle_memory(agent_name, action='hide', memory_ids='...') to hide "
            "outdated or redundant memories. This keeps agent context clean and focused.\n"
        )

    # Uploaded resources
    system = inject_resources_into_system(system, context.resources, context.lab.id)

    # Output files
    system = inject_output_files(system, context.lab.id)

    # Budget awareness
    budget_parts = []
    budget_parts.append(f"Iteration {context.iteration}")
    if context.lab.max_iterations:
        budget_parts[-1] += f"/{context.lab.max_iterations}"
    if context.elapsed_sec > 0:
        budget_parts.append(f"elapsed {int(context.elapsed_sec)}s")
        if context.lab.max_duration_sec:
            budget_parts[-1] += f"/{context.lab.max_duration_sec}s"
    system += f"\n\n**Budget**: {' | '.join(budget_parts)}\n"

    return system


def build_messages_from_history(
    context: "LoopContext",
    last_results: list[TaskResult],
    injections: list[str],
    *,
    prompt_suffix: str = "What's next?",
    first_iter_prompt: str = "Begin working on the lab objective.",
    max_history: int = 30,
) -> list[dict]:
    """Build the message history portion shared by all strategies.

    Returns messages WITHOUT the system message (caller prepends it).
    """
    messages: list[dict] = []

    for msg in context.messages[-max_history:]:
        if msg.sender_type == "user":
            messages.append({"role": "user", "content": msg.content})
        elif msg.sender_type == "orchestrator" and msg.message_type == "message":
            messages.append({"role": "assistant", "content": msg.content})
        elif msg.sender_type == "agent" and msg.message_type == "result":
            messages.append(
                {
                    "role": "user",
                    "content": f"[Agent {msg.sender_name} result]: {msg.content}",
                }
            )
        elif msg.message_type == "inject":
            messages.append(
                {
                    "role": "user",
                    "content": f"[USER INSTRUCTION]: {msg.content}",
                }
            )

    if last_results:
        results_text = "\n".join(
            f"- {r.agent_name}: {r.response[:500]}"
            if not r.error
            else f"- {r.agent_name}: ERROR: {r.error}"
            for r in last_results
        )
        messages.append(
            {
                "role": "user",
                "content": f"Agent results from iteration {context.iteration - 1}:\n{results_text}\n\n{prompt_suffix}",
            }
        )

    for inj in injections:
        messages.append({"role": "user", "content": f"[USER INSTRUCTION]: {inj}"})

    if context.iteration == 0 and not last_results:
        user_msgs = [m for m in context.messages if m.sender_type == "user"]
        if not user_msgs:
            messages.append({"role": "user", "content": first_iter_prompt})

    # Attach image resources to the last user message
    attach_resource_images(messages, context.resources, context.lab.id)

    return messages


def inject_resources_into_system(system: str, resources: list, lab_id) -> str:
    """Append uploaded resource listing to a system prompt.

    Only file metadata is included (name, type, size).
    Agents must use file_read(path) to access actual content.
    Images are listed by name/type (actual bytes go via attach_resource_images).
    """
    if not resources:
        return system

    file_parts: list[str] = []
    image_parts: list[str] = []

    for res in resources:
        if res.resource_type == "image":
            image_parts.append(
                f"- {res.original_name} ({res.content_type}, {res.size_bytes} bytes)"
            )
        else:
            desc = f" — {res.description}" if res.description else ""
            file_parts.append(
                f"- {res.original_name} ({res.resource_type}, {res.size_bytes} bytes){desc}"
            )

    if file_parts:
        system += "\n\n<uploaded_resources>\n"
        system += "\n".join(file_parts)
        system += '\nUse file_read(path="<filename>") to read resource content when needed.'
        system += "\n</uploaded_resources>"

    if image_parts:
        system += "\n\n<images>\n"
        system += "\n".join(image_parts)
        system += (
            "\nImage files are attached to the user message below for visual analysis.\n</images>"
        )

    return system


def attach_resource_images(messages: list[dict], resources: list, lab_id) -> list[dict]:
    """Attach base64-encoded image resources to the LAST user message.

    Modifies messages in-place and returns the same list.
    """
    if not resources:
        return messages

    image_b64: list[str] = []
    for res in resources:
        if res.resource_type == "image":
            file_path = LAB_RESOURCES_ROOT / str(lab_id) / res.filename
            if file_path.is_file():
                try:
                    raw = file_path.read_bytes()
                    b64 = base64.b64encode(raw).decode()
                    ct = res.content_type or "image/png"
                    image_b64.append(f"data:{ct};base64,{b64}")
                except Exception:
                    logger.warning("Failed to read image resource %s", res.filename)

    if image_b64:
        # Find last user message and attach images
        for msg in reversed(messages):
            if msg.get("role") == "user":
                msg.setdefault("images", []).extend(image_b64)
                break

    return messages
