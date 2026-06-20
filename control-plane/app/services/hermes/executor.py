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
from app.services.hermes.resources import build_resource_payload, persist_hermes_outputs
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
    resources=None,
    lab_id=None,
    timeout_sec: int | None = None,
) -> dict:
    """Delegate one task to the agent's Hermes container and await the reply.

    Lazily pops the container if needed (so a run works without pre-activation),
    resolves the agent's model_id to a concrete provider connection per run
    (model switches in the UI take effect immediately), and serializes turns
    per container (Hermes is a single-loop agent).

    ``resources`` (the lab's ``LabResource`` rows) are read off the shared volume
    and shipped to the agent's OWN container as input files; files the agent
    writes back are persisted to lab ``lab_id``'s output dir (existing OUTPUTS
    panel). Both default off, so the per-agent cron path is unaffected.
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

    # Read the lab's uploaded files off the shared volume into a base64 payload
    # the adapter writes into the agent's private container (it can't see the
    # lab_resources volume itself — that isolation is deliberate).
    resource_payload = build_resource_payload(resources) if resources else None

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
            resources=resource_payload,
            timeout_sec=timeout_sec or settings.hermes_default_timeout_sec,
        )
    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist anything the agent produced into the lab's output dir so the
    # existing OUTPUTS panel + download endpoint surface it (no new wiring).
    steps = res.get("steps") or []
    outputs = res.get("outputs") or []
    if outputs and lab_id is not None:
        written = persist_hermes_outputs(lab_id, outputs)
        if written:
            steps = [*steps, {"type": "outputs", "files": written}]
    elif outputs:
        logger.warning(
            "Hermes agent '%s' returned %d output file(s) but no lab_id to persist them",
            agent.name,
            len(outputs),
        )

    # Auto-activate: a Hermes agent that has cron jobs must stay always-on so the
    # control-plane scheduler can tick them; clear the flag when the last job is
    # gone. Persisted so the scheduler's reconcile restores the container after a
    # bob-api restart. Guarded so a flag write never fails the turn.
    cron_jobs = int(res.get("cron_jobs") or 0)
    desired = cron_jobs > 0
    if bool(getattr(agent, "hermes_activated", False)) != desired:
        try:
            agent.hermes_activated = desired
            await db.commit()
            logger.info(
                "Hermes agent '%s' hermes_activated=%s (cron_jobs=%d)",
                agent.name,
                desired,
                cron_jobs,
            )
        except Exception:  # noqa: BLE001 — never fail the turn over the activation flag
            await db.rollback()

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
        "cron_jobs": cron_jobs,
        # Per-round flow metadata (tools used, reasoning previews, markers) —
        # surfaced to the operator via the lab message's `extra`.
        "hermes_steps": steps,
    }
