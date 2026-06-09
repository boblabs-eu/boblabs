"""Cluster M — every RAG route has Depends(get_current_user).

The original audit found several RAG routes missing explicit auth deps —
they relied on FastAPI inheriting the router-level dependency, which had
been removed at some point. Fix: each route declares its own
`Depends(get_current_user)`.

This test introspects the FastAPI route table for the RAG router and
asserts the dep is present on every route.

It also asserts the SSRF guard is plumbed into the URL-ingestion path
(cluster M's other half) by spot-checking that `_fetch_webpage_text_http`
goes through `ssrf_guard.safe_get`.
"""

from __future__ import annotations

import pytest
from app.api.dependencies import get_current_user
from app.api.routes import rag as rag_module

pytestmark = pytest.mark.regression


def _route_dependencies(route):
    """Return the set of dep functions on a starlette/FastAPI route."""
    deps: set = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return deps
    # Walk the full dependant tree (dependencies on dependencies).
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            deps.add(d.call)
        stack.extend(d.dependencies)
    return deps


def test_every_rag_route_has_get_current_user_dep():
    """Introspect the RAG router and assert get_current_user is on every route.

    A few routes (background-task webhooks, etc.) MAY legitimately skip
    auth — they should be added to the exemption set explicitly and a
    comment justifies each. None today.
    """
    missing = []
    for route in rag_module.router.routes:
        path = getattr(route, "path", "")
        if not hasattr(route, "dependant"):
            continue  # WebSocket / Mount / etc.
        deps = _route_dependencies(route)
        if get_current_user not in deps:
            missing.append(path)
    assert not missing, f"RAG routes missing Depends(get_current_user): {missing}"


def test_rag_url_ingest_uses_ssrf_safe_get():
    """The cluster-M fix re-routes the webpage fetcher through ssrf_guard."""
    import inspect

    src = inspect.getsource(rag_module._fetch_webpage_text_http)
    assert "_ssrf_safe_get" in src or "safe_get" in src, (
        "_fetch_webpage_text_http no longer calls ssrf_guard.safe_get — cluster M regression"
    )
