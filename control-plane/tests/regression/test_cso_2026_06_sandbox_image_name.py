"""Regression: lab sandbox launch must work on any clone directory name.

control-plane/app/services/container_manager.py hardcodes
SANDBOX_IMAGE='bob-manager-bob-sandbox:latest' (env-overridable). For
this to actually resolve, docker compose must tag the built sandbox
image as `bob-manager-bob-sandbox` — which only happens if the compose
project name is pinned. Otherwise a clone into `boblabs/` (or any other
directory) builds `<dirname>-bob-sandbox` and `docker pull` 404's on
the hardcoded name, so every lab Run hits 500.

These tests pin both invariants:
1. docker-compose.yml must declare `name: bob-manager`.
2. container_manager.py must still default to the matching image name.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_docker_compose_pins_project_name() -> None:
    """docker-compose.yml must pin the project name so image prefixes are stable.

    Inside the test container the repo root isn't mounted, so we search a few
    candidate locations. Skip cleanly if the file isn't reachable — the test
    is a guardrail for local + CI runs that have the repo on disk.
    """
    candidates = [
        Path(__file__).resolve().parents[3] / "docker-compose.yml",  # repo root
        Path("/repo/docker-compose.yml"),
        Path("/workspace/docker-compose.yml"),
    ]
    compose = next((p for p in candidates if p.exists()), None)
    if compose is None:
        pytest.skip("docker-compose.yml not on disk in this runner")
    src = compose.read_text()
    assert "\nname: bob-manager\n" in src, (
        "docker-compose.yml must declare `name: bob-manager` at the top level — "
        "otherwise clones into differently-named directories produce "
        "`<dirname>-bob-sandbox` image tags that container_manager.py can't find. "
        "See CHANGELOG 0.12.3."
    )


def test_container_manager_default_matches_compose_image_prefix() -> None:
    """SANDBOX_IMAGE default must match what docker-compose builds."""
    cm = Path(__file__).resolve().parents[2] / "app" / "services" / "container_manager.py"
    src = cm.read_text()
    assert (
        'SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "bob-manager-bob-sandbox:latest")' in src
    ), "container_manager.py default must match the pinned compose project name"
