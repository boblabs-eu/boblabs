"""Bob Manager Agent — Systemctl service inspector."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def get_all_services() -> list[dict]:
    """Return all systemctl services with their states.

    Each service dict contains:
        name, load_state, active_state, sub_state, description.
    """
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("systemctl failed: %s", result.stderr)
            return []

        services = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4:
                services.append(
                    {
                        "name": parts[0].replace(".service", ""),
                        "load_state": parts[1],
                        "active_state": parts[2],
                        "sub_state": parts[3],
                        "description": parts[4] if len(parts) > 4 else "",
                    }
                )

        return services

    except FileNotFoundError:
        logger.warning("systemctl not found")
        return []
    except Exception as e:
        logger.error("Error getting services: %s", e)
        return []


def get_services_grouped() -> dict:
    """Return services grouped by state."""
    services = get_all_services()
    groups = {
        "running": [],
        "enabled": [],
        "disabled": [],
        "stopped": [],
        "failed": [],
        "other": [],
    }

    for svc in services:
        if svc["sub_state"] == "running":
            groups["running"].append(svc)
        elif svc["sub_state"] == "failed":
            groups["failed"].append(svc)
        elif svc["active_state"] == "inactive":
            groups["stopped"].append(svc)
        elif svc["load_state"] == "loaded":
            groups["enabled"].append(svc)
        else:
            groups["other"].append(svc)

    return groups
