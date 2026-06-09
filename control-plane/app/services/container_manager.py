"""Per-lab sandbox container lifecycle management (Option B).

Each lab gets its own isolated Docker container for code execution
(python_exec, shell_exec). Containers are created on lab run,
destroyed on lab delete/reset, and auto-created lazily if missing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

import docker
import docker.errors
import httpx

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "bob-manager-bob-sandbox:latest")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "bob-manager_bob-network")
LAB_RESOURCES_VOLUME = os.environ.get("LAB_RESOURCES_VOLUME", "bob-manager_lab_resources")
CONTAINER_MEM_DEFAULT = int(os.environ.get("SANDBOX_MEM_MB", "512"))
CONTAINER_CPUS_DEFAULT = float(os.environ.get("SANDBOX_CPUS", "1.0"))
SANDBOX_LABEL = "bob-manager.role=lab-sandbox"


def _name(lab_id: UUID) -> str:
    return f"bob-lab-{str(lab_id)[:12]}"


def _client() -> docker.DockerClient:
    return docker.from_env()


# ── Public API ──────────────────────────────────────────


async def ensure_sandbox(
    lab_id: UUID,
    memory_mb: int = CONTAINER_MEM_DEFAULT,
    cpus: float = CONTAINER_CPUS_DEFAULT,
) -> str:
    """Ensure a per-lab sandbox container is running. Returns base URL."""
    name = _name(lab_id)
    client = _client()

    try:
        container = await asyncio.to_thread(client.containers.get, name)
        if container.status != "running":
            await asyncio.to_thread(container.start)
            await _wait_healthy(name)
        return f"http://{name}:9000"
    except docker.errors.NotFound:
        pass

    await asyncio.to_thread(
        client.containers.run,
        SANDBOX_IMAGE,
        name=name,
        detach=True,
        network=DOCKER_NETWORK,
        volumes={LAB_RESOURCES_VOLUME: {"bind": "/data/lab_resources", "mode": "rw"}},
        mem_limit=f"{memory_mb}m",
        nano_cpus=int(cpus * 1e9),
        labels={
            "bob-manager.role": "lab-sandbox",
            "bob-manager.lab-id": str(lab_id),
        },
    )

    await _wait_healthy(name)
    logger.info(
        "Created sandbox %s for lab %s (mem=%dMB, cpus=%.1f)", name, lab_id, memory_mb, cpus
    )
    return f"http://{name}:9000"


async def destroy_sandbox(lab_id: UUID) -> None:
    """Stop and remove the sandbox container for a lab."""
    name = _name(lab_id)
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        await asyncio.to_thread(container.remove, force=True)
        logger.info("Destroyed sandbox %s for lab %s", name, lab_id)
    except docker.errors.NotFound:
        pass


async def stop_sandbox(lab_id: UUID) -> None:
    """Stop (but don't remove) the sandbox container."""
    name = _name(lab_id)
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        if container.status == "running":
            await asyncio.to_thread(container.stop, timeout=5)
            logger.info("Stopped sandbox %s for lab %s", name, lab_id)
    except docker.errors.NotFound:
        pass


async def get_sandbox_url(lab_id: UUID) -> str | None:
    """Return sandbox URL if the container exists and is running."""
    name = _name(lab_id)
    client = _client()
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        if container.status == "running":
            return f"http://{name}:9000"
    except docker.errors.NotFound:
        pass
    return None


async def cleanup_orphaned() -> int:
    """Remove all lab-sandbox containers. Call on API startup."""
    client = _client()
    containers = await asyncio.to_thread(
        client.containers.list,
        all=True,
        filters={"label": "bob-manager.role=lab-sandbox"},
    )
    removed = 0
    for c in containers:
        try:
            await asyncio.to_thread(c.remove, force=True)
            removed += 1
        except Exception:
            pass
    if removed:
        logger.info("Cleaned up %d orphaned sandbox containers", removed)
    return removed


# ── Internal ────────────────────────────────────────────


async def _wait_healthy(name: str, timeout: float = 30.0) -> None:
    url = f"http://{name}:9000/health"
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Sandbox container {name} not healthy after {timeout}s")
