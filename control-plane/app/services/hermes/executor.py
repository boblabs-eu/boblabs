"""One full Hermes turn — the shared entry point for every dispatch path.

Used by ``lab_runner._call_agent`` (solo + multi-agent labs) and by
``lab_scheduler._execute_agent_cron`` (per-agent cron). Returns the SAME dict
shape as ``LabDispatcher.call_agent`` (content / tokens_in / tokens_out /
model / provider / duration_ms, never ``tool_calls``) so the callers' existing
persistence, broadcast, and TaskResult code runs unchanged.

Callers must also force the agent's Bob Lab tool list empty on this path:
Hermes runs its own tools inside its container, and parsing Hermes' free-text
reply for ``<tool_call>`` blocks would let its output trigger Bob Lab tools.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.hermes.client import run_hermes_task
from app.services.hermes.resolver import resolve_model_identifier, resolve_model_spec
from app.services.hermes.runtime import ensure_hermes, hermes_run_lock

logger = logging.getLogger(__name__)


def is_hermes_agent(agent) -> bool:
    """True when a LabAgent/LibraryAgent row is hermes-backed."""
    return (getattr(agent, "backend", "native") or "native") == "hermes"


def hermes_container_key(agent):
    """Container key: the instance's own id, so every instance gets its OWN
    container + named volume and therefore isolated native memory (MEMORY.md,
    USER.md, skills, SOUL.md, sessions). The library agent is the shared
    *definition*, not a shared brain — instances of one template never mix
    memory."""
    return agent.id


async def execute_hermes_turn(
    db: AsyncSession,
    agent,
    instruction: str,
    *,
    timeout_sec: int | None = None,
) -> dict:
    """Delegate one task to the agent's Hermes container and await the reply.

    Lazily pops the container if needed (so a run works without pre-activation),
    resolves the agent's model_id to a concrete provider connection per run
    (model switches in the UI take effect immediately), and serializes turns
    per container (Hermes is a single-loop agent).
    """
    key = hermes_container_key(agent)
    url = await ensure_hermes(key)

    if settings.hermes_use_gateway:
        # Route Hermes' inference through the internal LLM gateway: every
        # model call goes through the LabDispatcher (load balancing across
        # all providers hosting the model, concurrency slots, affinity,
        # failover) and shows up in the LLM-event feed. The path tag is this
        # agent's id so the feed displays which Hermes agent is calling.
        identifier = await resolve_model_identifier(db, agent.model_id)
        gateway = settings.hermes_gateway_url.rstrip("/")
        model_spec = {
            "provider_type": "openai",
            "base_url": f"{gateway}/api/v1/llm-gateway/{agent.id}/v1",
            "api_key": settings.agent_secret,
            "model_identifier": identifier,
        }
    else:
        # Legacy/direct mode: hand Hermes the provider connection itself
        # (bypasses the dispatcher — no feed events, no load balancing).
        model_spec = await resolve_model_spec(db, agent.model_id)

    lock = await hermes_run_lock(key)
    start = time.monotonic()
    async with lock:
        res = await run_hermes_task(
            url,
            system_prompt=agent.system_prompt or "",
            instruction=instruction,
            model=model_spec,
            # Per-instance session id — the container is already isolated per
            # instance, but this also namespaces the adapter's own transcript
            # (bob_sessions/<sid>.json) instead of the shared "boblab" default.
            options={"session_id": str(agent.id)},
            timeout_sec=timeout_sec or settings.hermes_default_timeout_sec,
        )
    duration_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "Hermes turn done for agent '%s' (model=%s, %dms)",
        agent.name,
        model_spec["model_identifier"],
        duration_ms,
    )
    return {
        "content": res["content"],
        "tokens_in": res["tokens_in"],
        "tokens_out": res["tokens_out"],
        "model": model_spec["model_identifier"],
        "provider": "hermes",
        "duration_ms": duration_ms,
        # Per-round flow metadata (tools used, reasoning previews, markers) —
        # surfaced to the operator via the lab message's `extra`.
        "hermes_steps": res.get("steps") or [],
    }
