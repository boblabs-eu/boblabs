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
    cm = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "container_manager.py"
    )
    src = cm.read_text()
    assert (
        'SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "bob-manager-bob-sandbox:latest")'
        in src
    ), "container_manager.py default must match the pinned compose project name"


def test_deploy_prod_sh_builds_sandbox_image() -> None:
    """deploy-prod.sh is the canonical install path; it must build bob-sandbox.

    bob-sandbox is `profiles: [build-only]` (kept that way intentionally —
    docker compose up doesn't start it). The image MUST get built via
    deploy-prod.sh, otherwise the first lab Run 500s because
    container_manager.py asks Docker for an image that was never built.
    """
    candidates = [
        Path(__file__).resolve().parents[3] / "deploy-prod.sh",
        Path("/repo/deploy-prod.sh"),
        Path("/workspace/deploy-prod.sh"),
    ]
    deploy_sh = next((p for p in candidates if p.exists()), None)
    if deploy_sh is None:
        pytest.skip("deploy-prod.sh not on disk in this runner")
    src = deploy_sh.read_text()
    assert "$COMPOSE build bob-sandbox" in src, (
        "deploy-prod.sh must explicitly `docker compose build bob-sandbox` — "
        "the service has `profiles: [build-only]` so plain `up --build` skips it. "
        "Without this line, first-install lab Run 500s."
    )


def test_deploy_prod_sh_chowns_volumes_to_uid_1000() -> None:
    """deploy-prod.sh must chown lab_resources + qdrant_staging to 1000:1000.

    CSO #3 dropped root for bob-api + bob-sandbox (both run as UID 1000).
    Docker volumes that were ever written by a pre-CSO #3 (root) container
    keep root ownership, which causes Errno 13 on every lab/agent Run.
    deploy-prod.sh's Step 2.5 self-heals this; without that step, upgrades
    from any pre-CSO #3 release break lab Run + agent Run. See CHANGELOG 0.12.5.
    """
    candidates = [
        Path(__file__).resolve().parents[3] / "deploy-prod.sh",
        Path("/repo/deploy-prod.sh"),
        Path("/workspace/deploy-prod.sh"),
    ]
    deploy_sh = next((p for p in candidates if p.exists()), None)
    if deploy_sh is None:
        pytest.skip("deploy-prod.sh not on disk in this runner")
    src = deploy_sh.read_text()
    assert "bob-manager_lab_resources:/lab_resources" in src, (
        "deploy-prod.sh must mount bob-manager_lab_resources for the chown step"
    )
    assert "bob-manager_qdrant_staging:/qdrant_staging" in src, (
        "deploy-prod.sh must mount bob-manager_qdrant_staging for the chown step"
    )
    assert "alpine:3.20" in src, (
        "deploy-prod.sh must use a PINNED alpine tag (alpine:3.20), not :latest"
    )
    assert "chown -R 1000:1000" in src, (
        "deploy-prod.sh must chown the named volumes to 1000:1000 — "
        "otherwise pre-CSO #3 upgrades hit Errno 13 on every lab/agent Run."
    )
