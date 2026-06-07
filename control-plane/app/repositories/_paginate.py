"""Shared pagination clamp for repository list methods (Phase 5 Session 2).

Audit follow-ups P03 (unbounded `get_injections`), P04 (unbounded
`get_all` across several repos) and P05 (caller-controlled paginators
with no upper cap) all need the same defence: never let a single SQL
query return more than ``MAX_LIMIT`` rows.

Repos import :func:`clamp_limit` and pass `limit=clamp_limit(limit)`
into the SQL builder. The default cap is 500, which covers normal UI
paginations (typically ≤100) and admin sweeps without putting tens of
thousands of rows on the wire in one call.
"""

from __future__ import annotations

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def clamp_limit(limit: int | None, max_limit: int = MAX_LIMIT) -> int:
    """Return a non-negative ``limit`` <= ``max_limit``.

    None / negative / zero → ``max_limit`` (treat as "give me as much
    as you'll allow"). Caller-supplied values are clamped to the cap.
    """
    if limit is None or limit <= 0:
        return max_limit
    return min(limit, max_limit)
