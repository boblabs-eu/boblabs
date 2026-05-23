"""Bob Manager Agent — Script Runner discovery collector.

Queries a local Bob Script Runner instance for available scripts
and reports them to the control plane.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def get_script_runner_scripts(base_url: str) -> list[dict]:
    """Query the local script runner for available scripts (synchronous).

    Returns list of script metadata dicts, or empty list on failure.
    """
    if not base_url:
        return []
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url.rstrip('/')}/scripts")
            resp.raise_for_status()
            data = resp.json()

        # Endpoint returns a list directly
        if isinstance(data, list):
            return data
        # Fallback for dict wrapper
        return data.get("scripts", [])

    except Exception as e:
        logger.warning("Script runner not available at %s: %s", base_url, e)
        return []
