"""Bob Manager — Hermes agent backend lifecycle API.

Mounted at /api/v1. Lets the operator pop/stop/inspect the per-agent Hermes
container from the agent edit UI. Runs also lazy-ensure the container, so
activation here is a convenience (pre-warm + health visibility), not a
requirement.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import DbSession, require_admin
from app.repositories.lab_repo import LabAgentRepository, LibraryAgentRepository
from app.services.hermes import (
    HermesNotConfiguredError,
    destroy_hermes,
    ensure_hermes,
    get_hermes_status,
    hermes_container_key,
    stop_hermes,
)

router = APIRouter(prefix="/library-agents", tags=["hermes"])


async def _resolve_agent(db, agent_id: UUID):
    """Accept a library-agent id OR a (standalone) lab-agent id.

    The UI's HermesPanel passes `agent.library_agent_id || agent.id`, so for an
    ad-hoc lab agent (created directly in a lab, no template) the id is a
    lab_agents row. Resolve both and return (agent, container_key) — the key
    matches what the executor uses (`hermes_container_key`).
    """
    agent = await LibraryAgentRepository(db).get_by_id(agent_id)
    if agent:
        return agent, agent.id
    lab_agent = await LabAgentRepository(db).get_by_id(agent_id)
    if lab_agent:
        return lab_agent, hermes_container_key(lab_agent)
    raise HTTPException(404, "Agent not found")


async def _get_hermes_agent(db, agent_id: UUID):
    agent, key = await _resolve_agent(db, agent_id)
    if (getattr(agent, "backend", "native") or "native") != "hermes":
        raise HTTPException(400, f"Agent '{agent.name}' is not hermes-backed")
    return agent, key


@router.post("/{agent_id}/hermes/activate")
async def activate_hermes(agent_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    """Pop (or start) the agent's Hermes container and wait until healthy."""
    _agent, key = await _get_hermes_agent(db, agent_id)
    try:
        url = await ensure_hermes(key)
    except HermesNotConfiguredError as exc:
        raise HTTPException(409, str(exc))
    except TimeoutError as exc:
        raise HTTPException(504, str(exc))
    except Exception as exc:  # noqa: BLE001 — docker daemon errors etc.
        raise HTTPException(502, f"Failed to start Hermes container: {exc}")
    return {"status": "running", "url": url}


@router.post("/{agent_id}/hermes/deactivate")
async def deactivate_hermes(agent_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    """Stop the agent's Hermes container (memory volume is kept)."""
    _agent, key = await _get_hermes_agent(db, agent_id)
    stopped = await stop_hermes(key)
    return {"status": "stopped" if stopped else "not_running"}


@router.delete("/{agent_id}/hermes/container")
async def remove_hermes_container(
    agent_id: UUID, db: DbSession, _user: dict = Depends(require_admin)
):
    """Remove the container entirely (the ~/.hermes memory volume is kept)."""
    _agent, key = await _get_hermes_agent(db, agent_id)
    await destroy_hermes(key)
    return {"status": "removed"}


@router.get("/{agent_id}/hermes/status")
async def hermes_status(agent_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    """Container status for the agent-edit UI panel."""
    agent, key = await _resolve_agent(db, agent_id)
    status = await get_hermes_status(key)
    status["backend"] = getattr(agent, "backend", "native") or "native"
    return status
