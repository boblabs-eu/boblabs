"""Bob Manager Agent — Docker container collector.

Lists running/stopped containers with resource usage via `docker` CLI.
Requires the agent user to be in the `docker` group.
"""

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def get_docker_containers() -> list[dict[str, Any]]:
    """Return all Docker containers with status info.

    Each container dict contains:
        id, name, image, status, state, created, ports.
    """
    try:
        result = subprocess.run(
            [
                "docker", "ps", "-a",
                "--format", "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("docker ps failed: %s", result.stderr.strip())
            return []

        containers = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            try:
                c = json.loads(line)
                containers.append({
                    "id": c.get("ID", "")[:12],
                    "name": c.get("Names", ""),
                    "image": c.get("Image", ""),
                    "status": c.get("Status", ""),
                    "state": c.get("State", ""),
                    "created": c.get("CreatedAt", ""),
                    "ports": c.get("Ports", ""),
                })
            except json.JSONDecodeError:
                continue
        return containers

    except FileNotFoundError:
        logger.debug("docker not found on this system")
        return []
    except Exception as e:
        logger.warning("Docker collector error: %s", e)
        return []


def get_docker_stats() -> list[dict[str, Any]]:
    """Return resource usage for running containers.

    Each dict contains:
        name, cpu_percent, mem_usage, mem_limit, mem_percent, net_io, block_io, pids.
    """
    try:
        result = subprocess.run(
            [
                "docker", "stats", "--no-stream",
                "--format", "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []

        stats = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            try:
                s = json.loads(line)
                stats.append({
                    "name": s.get("Name", ""),
                    "cpu_percent": s.get("CPUPerc", "0%").rstrip("%"),
                    "mem_usage": s.get("MemUsage", ""),
                    "mem_percent": s.get("MemPerc", "0%").rstrip("%"),
                    "net_io": s.get("NetIO", ""),
                    "block_io": s.get("BlockIO", ""),
                    "pids": s.get("PIDs", "0"),
                })
            except json.JSONDecodeError:
                continue
        return stats

    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("Docker stats error: %s", e)
        return []
