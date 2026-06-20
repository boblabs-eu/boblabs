"""Bob Manager — Hermes external agent backend.

Self-contained module for running the real NousResearch Hermes agent as a
Bob Lab agent backend (``LabAgent.backend == 'hermes'``). Each hermes-backed
library agent gets its own Docker container (real Hermes + the bob
hermes-adapter — see ``hermes-adapter/ADAPTER_CONTRACT.md`` at the repo root)
that pops up on activation or lazily on first task, with a persistent
``~/.hermes`` volume so Hermes' memory/skills survive restarts.

The agent's existing ``model_id`` keeps its meaning: it is the LLM *Hermes*
uses — resolved per-run to a concrete provider connection and sent with each
task, so switching the model in the UI needs no container restart.
"""

from app.services.hermes.client import (
    HermesAdapterError,
    cron_output,
    cron_tick,
    hermes_health,
    run_hermes_task,
)
from app.services.hermes.executor import (
    execute_hermes_turn,
    hermes_container_key,
    is_hermes_agent,
)
from app.services.hermes.resolver import resolve_model_spec
from app.services.hermes.resources import build_resource_payload, persist_hermes_outputs
from app.services.hermes.runtime import (
    HermesNotConfiguredError,
    cleanup_orphaned_hermes,
    destroy_hermes,
    ensure_hermes,
    get_hermes_status,
    hermes_run_lock,
    stop_hermes,
)

__all__ = [
    "HermesAdapterError",
    "HermesNotConfiguredError",
    "build_resource_payload",
    "cleanup_orphaned_hermes",
    "cron_output",
    "cron_tick",
    "destroy_hermes",
    "ensure_hermes",
    "execute_hermes_turn",
    "persist_hermes_outputs",
    "get_hermes_status",
    "hermes_container_key",
    "hermes_health",
    "hermes_run_lock",
    "is_hermes_agent",
    "resolve_model_spec",
    "run_hermes_task",
    "stop_hermes",
]
