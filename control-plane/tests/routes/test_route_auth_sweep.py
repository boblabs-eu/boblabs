"""Route auth boundary sweep — every router gets introspected.

Catches the most common regression in Sessions 2–6: someone adds a new
route to a router that's supposed to be admin-only, forgets the
`Depends(require_admin)`, and ships a privilege escalation.

This file declares three contracts:

1. **PUBLIC_ROUTERS** — routers where every route is intentionally
   unauthenticated (`public`, `blog_seo`, `internal_apps` which uses
   HMAC, `auth` for the login endpoint). Adding a route to these
   modules that needs auth → change the contract.

2. **ADMIN_ONLY_ROUTERS** — every route MUST have `require_admin` in
   its dependant tree.

3. **AUTHENTICATED_ROUTERS** — every route MUST have at least one of:
   - `get_current_user`
   - `require_admin`
   - `require_infra_access`
   - HMAC verification (internal_apps style)

If a route's dependant tree has none of these, the sweep fails with
"open route detected".
"""

from __future__ import annotations

import importlib
import inspect

import pytest

pytestmark = pytest.mark.route_auth


# ── Contracts ──────────────────────────────────────────────────────


# Routers whose routes are PUBLIC by design.
PUBLIC_ROUTERS = {
    "public",  # /admin-login, /quote, /trial, /blog read
    "blog_seo",  # /blog/<slug>, /sitemap.xml, /rss.xml (SEO bots)
    "internal_apps",  # HMAC-protected (not JWT) — different auth model
    "auth",  # /login — issues JWT, can't require it
}

# Routers where every route MUST be admin-only.
ADMIN_ONLY_ROUTERS = {
    "admin_logs",
    "admin_consumer_apps",
    "admin_labs",
}

# All remaining routers go here automatically (computed below).


def _import_router(name: str):
    return importlib.import_module(f"app.api.routes.{name}")


def _route_dep_call_set(route) -> set:
    """Walk dependant tree → set of callable objects (deps)."""
    out: set = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return out
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            out.add(d.call)
        stack.extend(d.dependencies)
    return out


def _route_label(route) -> str:
    methods = ",".join(sorted(getattr(route, "methods", []) or {"?"}))
    path = getattr(route, "path", "?")
    name = getattr(route, "name", "?")
    return f"{methods} {path} ({name})"


# Discover all router modules.
import os

_ROUTES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "app",
    "api",
    "routes",
)
_ALL_ROUTER_NAMES = sorted(
    f[:-3] for f in os.listdir(_ROUTES_DIR) if f.endswith(".py") and f != "__init__.py"
)

AUTH_REQUIRED_ROUTERS = sorted(set(_ALL_ROUTER_NAMES) - PUBLIC_ROUTERS - ADMIN_ONLY_ROUTERS)


# ── ADMIN_ONLY assertions ──────────────────────────────────────────


@pytest.mark.parametrize("router_name", sorted(ADMIN_ONLY_ROUTERS))
def test_admin_only_router_every_route_requires_admin(router_name):
    """Every route in an admin-only router must have require_admin in
    its dependency tree."""
    from app.api.dependencies import require_admin

    mod = _import_router(router_name)
    bad: list[str] = []
    for route in mod.router.routes:
        deps = _route_dep_call_set(route)
        if require_admin not in deps:
            bad.append(_route_label(route))
    assert not bad, (
        f"{router_name} routes missing require_admin: {bad}. "
        f"If a route is intentionally non-admin, move it to a different "
        f"router or update PUBLIC_ROUTERS / AUTH_REQUIRED_ROUTERS."
    )


# ── KNOWN-OPEN snapshot ───────────────────────────────────────────
#
# These routes have NO auth dep today. Most are pre-existing oversights
# the audit's cluster work (A–R) did not target. Phase 5 Session 5/6 +
# follow-up audits will close them. For now we snapshot the current
# state so the sweep catches NEW opens (regression-only mode):
# any route added to one of these routers that ISN'T in the snapshot
# must have auth — that's the regression we're guarding.
#
# To close a route: add Depends(get_current_user) (or stricter) to the
# handler, then remove it from this snapshot. The sweep will start
# enforcing the dep going forward.

KNOWN_OPEN_ROUTES: dict[str, set[str]] = {
    "labs": {
        "/labs/strategies",
        "/labs/strategy-prompts/{loop_type}",
        "/labs/agents/library",
        "/labs/{lab_id}/agents",
        "/labs/{lab_id}/agents/{agent_id}",
        "/labs/{lab_id}/tools",
        "/labs/{lab_id}/tools/{tool_id}",
        "/labs/{lab_id}/memories/{memory_id}",
        "/labs/{lab_id}/resources",
        "/labs/{lab_id}/resources/{resource_id}/download",
        "/labs/{lab_id}/resources/{resource_id}",
        "/labs/{lab_id}/resources/{resource_id}/content",
        "/labs/{lab_id}/output-files",
        "/labs/{lab_id}/output-files/download",
        "/labs/{lab_id}/output-files/content",
        "/labs/{lab_id}/output-files/history",
    },
    "labs_files": {
        "/{lab_id}/memories/{memory_id}",
        "/{lab_id}/resources",
        "/{lab_id}/resources/{resource_id}/download",
        "/{lab_id}/resources/{resource_id}",
        "/{lab_id}/resources/{resource_id}/content",
        "/{lab_id}/output-files",
        "/{lab_id}/output-files/download",
        "/{lab_id}/output-files/content",
        "/{lab_id}/output-files/history",
    },
    "library_agents": {
        "/library-agents",
        "/library-agents/instances",
        "/library-agents/{agent_id}/instances",
        "/library-agents/instances/{lab_id}",
        "/library-agents/instances/{lab_id}/run",
        "/library-agents/instances/{lab_id}/pause",
        "/library-agents/instances/{lab_id}/resume",
        "/library-agents/instances/{lab_id}/stop",
        "/library-agents/instances/{lab_id}/inject",
        "/library-agents/{agent_id}",
        "/library-agents/{agent_id}/duplicate",
        "/library-agents/{agent_id}/labs",
        "/library-agents/{agent_id}/stats",
    },
    "metrics": {
        "/metrics",
        "/metrics/{server_name}",
    },
    "news": {
        "/news/",
        "/news/sources",
    },
    "orchestrator": {
        "/orchestrator/settings",
        "/orchestrator/providers/types",
        "/orchestrator/providers",
        "/orchestrator/providers/{provider_id}",
        "/orchestrator/providers/{provider_id}/test",
        "/orchestrator/models",
        "/orchestrator/models/unique",
        "/orchestrator/models/live",
        "/orchestrator/models/sync",
        "/orchestrator/agents",
        "/orchestrator/agents/{agent_id}",
        "/orchestrator/tasks",
        "/orchestrator/builtin-tools",
        "/orchestrator/pipelines",
    },
    "projects": {
        "/projects/themes",
        "/projects/themes/rename",
        "/projects/themes/{theme_name}/color",
        "/projects/{project_id}/resources",
    },
    "resources": {
        "/resources/{resource_id}/projects",
        "/resources/{resource_id}/projects/{project_id}",
    },
    "web3": {
        "/web3/prices",
    },
}


# ── AUTH_REQUIRED assertions ───────────────────────────────────────


@pytest.mark.parametrize("router_name", AUTH_REQUIRED_ROUTERS)
def test_authenticated_router_every_route_has_auth_dep(router_name):
    """Every route in a non-public router must either have an auth dep
    OR be in the KNOWN_OPEN_ROUTES snapshot.

    New routes without auth → fail. Pre-existing opens → tracked.
    """
    from app.api.dependencies import get_current_user, require_admin
    from app.services.authorization import require_infra_access

    accepted_deps = {get_current_user, require_admin, require_infra_access}
    known_open = KNOWN_OPEN_ROUTES.get(router_name, set())

    mod = _import_router(router_name)
    new_open: list[str] = []
    for route in mod.router.routes:
        deps = _route_dep_call_set(route)
        if deps & accepted_deps:
            continue
        path = getattr(route, "path", "?")
        if path in known_open:
            continue
        new_open.append(_route_label(route))
    assert not new_open, (
        f"{router_name} has NEW open routes (not in KNOWN_OPEN_ROUTES "
        f"snapshot): {new_open}. Either add auth to the route or add "
        f"it to the snapshot with an issue-tracker reference."
    )


# ── PUBLIC routers don't accidentally become locked ────────────────


@pytest.mark.parametrize("router_name", sorted(PUBLIC_ROUTERS))
def test_public_router_module_imports(router_name):
    """Smoke: the router imports without error and exposes `router`."""
    mod = _import_router(router_name)
    assert hasattr(mod, "router")


# ── Cross-router targeted HTTP probes ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/labs",
        "/api/v1/servers",
        "/api/v1/projects",
        "/api/v1/rag/collections",
        "/api/v1/access-tokens",
    ],
)
async def test_anonymous_blocked_on_authenticated_route(anonymous_client, path):
    """Spot-check anonymous access against a handful of routes —
    confirms the dep wires up over HTTP, not just at the introspection
    layer."""
    r = await anonymous_client.get(path)
    assert r.status_code in (401, 403), (
        f"{path} returned {r.status_code} for anonymous; expected 401/403"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/labs",
        "/api/v1/admin/consumer-apps",
        "/api/v1/admin/logs/requests",  # admin_logs has no root route, only sub-paths
    ],
)
async def test_non_admin_blocked_on_admin_route(user_client, path):
    r = await user_client.get(path)
    assert r.status_code == 403, f"{path} returned {r.status_code} for non-admin; expected 403"


# ── Module-level sanity ────────────────────────────────────────────


def test_no_router_left_unclassified():
    """If a new router file lands and isn't in PUBLIC_ROUTERS or
    ADMIN_ONLY_ROUTERS, it goes through AUTH_REQUIRED_ROUTERS — which
    means it must have auth. This test asserts the buckets cover the
    full set."""
    covered = PUBLIC_ROUTERS | ADMIN_ONLY_ROUTERS | set(AUTH_REQUIRED_ROUTERS)
    missing = set(_ALL_ROUTER_NAMES) - covered
    assert not missing, (
        f"Routers not classified: {missing}. Add to PUBLIC_ROUTERS, "
        f"ADMIN_ONLY_ROUTERS, or accept the default AUTH_REQUIRED."
    )
