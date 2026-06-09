"""CSO Findings #1 + #2 — /api/v1/metrics router-level auth gate.

Pre-fix: the `metrics` APIRouter had no `dependencies=[...]`. Both
routes (`GET /api/v1/metrics`, `GET /api/v1/metrics/{server_name}`)
were publicly reachable through the production nginx layout and
returned ~100 KB of per-agent reconnaissance (hostname, GPU model,
CPU temp, disk mounts, network throughput). See the CSO report at
.gstack/security-reports/2026-06-09-184351.json for the verified
exploit walkthrough.

Post-fix: the router declares
``dependencies=[Depends(require_infra_access)]`` at construction,
matching the existing pattern in commands.py / servers.py. This test
locks both the source shape (so a future commit doesn't accidentally
drop the gate) and the runtime behavior (anonymous request → 401/403,
not 200 with the recon payload).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_PATH = REPO_ROOT / "app" / "api" / "routes" / "metrics.py"


def _read_metrics_src() -> str:
    assert METRICS_PATH.is_file(), f"{METRICS_PATH} missing"
    return METRICS_PATH.read_text(encoding="utf-8")


# ── Source-introspection guards ──────────────────────────────────────


def test_cso_metrics_router_has_require_infra_access() -> None:
    src = _read_metrics_src()
    assert "from app.services.authorization import require_infra_access" in src, (
        "CSO #1: metrics.py must import require_infra_access"
    )
    # The router constructor must wire it as a router-level dependency
    # so both routes are protected by a single declaration.
    assert re.search(
        r"router\s*=\s*APIRouter\(\s*[^)]*dependencies\s*=\s*\[\s*Depends\(require_infra_access\)\s*\]",
        src,
        re.S,
    ), "CSO #1: metrics router must declare dependencies=[Depends(require_infra_access)]"


def test_cso_metrics_module_still_only_exposes_two_routes() -> None:
    """Belt-and-braces: any new route added here must inherit the gate
    via the router-level dependency. This test pins the route count so
    a future commit that adds a route also has to update this test,
    forcing a conscious review of the auth posture.
    """
    src = _read_metrics_src()
    decorators = re.findall(r"^@router\.(get|post|put|delete|patch)\(", src, re.M)
    assert len(decorators) == 2, (
        f"metrics.py route count drifted ({len(decorators)} != 2). If "
        "you added a route, update this test AND confirm the router-"
        "level require_infra_access still covers it."
    )


# ── Runtime behavior ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_request_to_metrics_is_rejected(anonymous_client) -> None:
    """CSO #1 — bare GET must not return the recon payload."""
    r = await anonymous_client.get("/api/v1/metrics")
    assert r.status_code in (401, 403), (
        f"Expected 401/403 from anonymous /metrics, got {r.status_code}: {r.text[:200]}"
    )


@pytest.mark.asyncio
async def test_anonymous_request_to_per_server_metrics_is_rejected(
    anonymous_client,
) -> None:
    """CSO #2 — the per-server variant must also reject anonymous access."""
    r = await anonymous_client.get("/api/v1/metrics/some-host")
    assert r.status_code in (401, 403), (
        f"Expected 401/403 from anonymous /metrics/{{server_name}}, "
        f"got {r.status_code}: {r.text[:200]}"
    )


@pytest.mark.asyncio
async def test_non_admin_request_to_metrics_is_rejected(user_client) -> None:
    """A logged-in non-admin user must not be able to read fleet metrics
    either — require_infra_access matches the gate used by commands.py
    and servers.py."""
    r = await user_client.get("/api/v1/metrics")
    assert r.status_code == 403, (
        f"Expected 403 from non-admin /metrics, got {r.status_code}: {r.text[:200]}"
    )
