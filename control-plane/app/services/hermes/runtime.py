"""Per-agent Hermes container lifecycle.

Mirrors the per-lab sandbox pattern in ``app/services/container_manager.py``:
lazy ensure, health-wait on the container's internal URL, labels for orphan
cleanup, stop/destroy. Differences:

- Keyed by **library_agent_id** (one Hermes per hermes-backed agent template;
  all lab instances of that template share its brain/memory).
- A **persistent named volume** ``bob-hermes-<id12>`` is mounted at
  ``/root/.hermes`` so Hermes' memory/skills/sessions survive container
  restarts and re-creates.
- ``destroy_hermes`` removes the CONTAINER ONLY. It must never call
  ``client.volumes.remove()`` — the docker-socket-proxy runs with
  ``VOLUMES: 0`` which gates the ``/volumes/*`` API (named-volume *mounts*
  via ``containers.run`` are fine; the daemon auto-creates them). The volume
  is intentionally left behind so re-activating the agent restores its memory.
- A per-key ``asyncio.Lock`` serializes task runs: Hermes is a single-loop
  agent; concurrent tasks from multiple labs queue rather than interleave.
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

import docker
import docker.errors
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "bob-manager_bob-network")
HERMES_LABEL_ROLE = "hermes-agent"
HERMES_MEM_MB = int(os.environ.get("HERMES_MEM_MB", "2048"))
HERMES_CPUS = float(os.environ.get("HERMES_CPUS", "2.0"))

# Per-agent run locks (Hermes is single-loop; serialize tasks per container).
_run_locks: dict[str, asyncio.Lock] = {}
_run_locks_guard = asyncio.Lock()

# Per-agent creation locks — two concurrent tasks ensuring the same container
# would both see NotFound and both call containers.run(), the loser dying on
# a duplicate-name APIError. Serialize the get-or-create per key.
_ensure_locks: dict[str, asyncio.Lock] = {}
_ensure_locks_guard = asyncio.Lock()


async def _ensure_lock(agent_key: UUID | str) -> asyncio.Lock:
    key = _name(agent_key)
    async with _ensure_locks_guard:
        if key not in _ensure_locks:
            _ensure_locks[key] = asyncio.Lock()
        return _ensure_locks[key]


class HermesNotConfiguredError(RuntimeError):
    """Raised when HERMES_IMAGE is not set — the feature is dormant."""

    def __init__(self) -> None:
        super().__init__(
            "Hermes image not configured. Set HERMES_IMAGE to the hermes-adapter "
            "image (see hermes-adapter/ADAPTER_CONTRACT.md) to enable the Hermes "
            "agent backend."
        )


def _key(agent_key: UUID | str) -> str:
    return str(agent_key)[:12]


def _name(agent_key: UUID | str) -> str:
    return f"bob-hermes-{_key(agent_key)}"


def _volume(agent_key: UUID | str) -> str:
    return f"bob-hermes-{_key(agent_key)}"


def _url(agent_key: UUID | str) -> str:
    return f"http://{_name(agent_key)}:{settings.hermes_internal_port}"


def _client() -> docker.DockerClient:
    return docker.from_env()


async def hermes_run_lock(agent_key: UUID | str) -> asyncio.Lock:
    """Get (or create) the serialization lock for one Hermes agent."""
    key = _name(agent_key)
    async with _run_locks_guard:
        if key not in _run_locks:
            _run_locks[key] = asyncio.Lock()
        return _run_locks[key]


# ── Public API ──────────────────────────────────────────


async def ensure_hermes(agent_key: UUID | str) -> str:
    """Ensure the Hermes container for this agent is running. Returns base URL.

    Raises HermesNotConfiguredError when no image is configured — callers
    surface that as a clear operator-facing error instead of crashing.
    """
    if not settings.hermes_image:
        raise HermesNotConfiguredError()

    name = _name(agent_key)
    client = _client()

    async with await _ensure_lock(agent_key):
        try:
            container = await asyncio.to_thread(client.containers.get, name)
            if container.status != "running":
                await asyncio.to_thread(container.start)
                await _wait_healthy(agent_key)
            return _url(agent_key)
        except docker.errors.NotFound:
            pass

        try:
            await asyncio.to_thread(
                client.containers.run,
                settings.hermes_image,
                name=name,
                detach=True,
                network=DOCKER_NETWORK,
                volumes={_volume(agent_key): {"bind": "/root/.hermes", "mode": "rw"}},
                # AGENT_SECRET lets the adapter authenticate Bob's cron-driving
                # calls (/v1/cron/tick, /v1/cron/output) — same shared token the
                # LLM gateway already uses.
                environment={"AGENT_SECRET": settings.agent_secret},
                mem_limit=f"{HERMES_MEM_MB}m",
                nano_cpus=int(HERMES_CPUS * 1e9),
                labels={
                    "bob-manager.role": HERMES_LABEL_ROLE,
                    "bob-manager.hermes-agent-id": str(agent_key),
                },
            )
        except docker.errors.APIError as exc:
            # Belt & braces: a racing creator outside this process (e.g. a
            # second worker) may have won — fall through to the existing
            # container instead of failing the task.
            if "Conflict" not in str(exc) and "already in use" not in str(exc):
                raise
            container = await asyncio.to_thread(client.containers.get, name)
            if container.status != "running":
                await asyncio.to_thread(container.start)

        await _wait_healthy(agent_key)
        logger.info(
            "Created Hermes container %s for agent %s (mem=%dMB, cpus=%.1f)",
            name,
            agent_key,
            HERMES_MEM_MB,
            HERMES_CPUS,
        )
        return _url(agent_key)


async def stop_hermes(agent_key: UUID | str) -> bool:
    """Stop (but don't remove) the Hermes container. Returns True if it was running."""
    name = _name(agent_key)
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        if container.status == "running":
            await asyncio.to_thread(container.stop, timeout=10)
            logger.info("Stopped Hermes container %s", name)
            return True
    except docker.errors.NotFound:
        pass
    return False


async def destroy_hermes(agent_key: UUID | str) -> None:
    """Remove the Hermes container. The ~/.hermes volume is deliberately kept
    (see module docstring) so the agent's memory survives re-activation."""
    name = _name(agent_key)
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        await asyncio.to_thread(container.remove, force=True)
        logger.info("Destroyed Hermes container %s (volume kept)", name)
    except docker.errors.NotFound:
        pass


async def get_hermes_status(agent_key: UUID | str) -> dict:
    """Status snapshot for the UI panel."""
    status: dict = {
        "image_configured": bool(settings.hermes_image),
        "running": False,
        "healthy": False,
        "url": None,
        "container": _name(agent_key),
    }
    if not settings.hermes_image:
        return status
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, _name(agent_key))
    except docker.errors.NotFound:
        return status
    except Exception as exc:  # noqa: BLE001 — docker daemon unreachable etc.
        status["error"] = str(exc)
        return status
    status["running"] = container.status == "running"
    if status["running"]:
        status["url"] = _url(agent_key)
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                r = await http.get(f"{_url(agent_key)}/health")
                status["healthy"] = r.status_code == 200
        except Exception:
            status["healthy"] = False
    return status


async def cleanup_orphaned_hermes() -> int:
    """Remove all hermes-agent containers (volumes kept). Call on API startup."""
    try:
        client = _client()
        containers = await asyncio.to_thread(
            client.containers.list,
            all=True,
            filters={"label": f"bob-manager.role={HERMES_LABEL_ROLE}"},
        )
    except Exception:  # docker unavailable — nothing to clean
        return 0
    removed = 0
    for c in containers:
        try:
            await asyncio.to_thread(c.remove, force=True)
            removed += 1
        except Exception:
            pass
    if removed:
        logger.info("Cleaned up %d orphaned Hermes containers (volumes kept)", removed)
    return removed


# ── Internal ────────────────────────────────────────────


async def _wait_healthy(agent_key: UUID | str, timeout: float = 90.0) -> None:
    """Hermes start can be slow (Python runtime + Hermes init) — generous wait."""
    url = f"{_url(agent_key)}/health"
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(1.0)
    raise TimeoutError(f"Hermes container {_name(agent_key)} not healthy after {timeout}s")
