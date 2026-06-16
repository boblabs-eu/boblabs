"""Regression: fresh install must reach Alembic head.

0.11.0–0.12.1 startup stamped `head` whenever init.sql had a known recent
column (blog_posts.slug). init.sql then drifted nine migrations behind the
chain, so fresh installs got the stale schema and Alembic refused to apply
the catch-up migrations — the orchestrator console crashed querying
columns that did not exist (ai_providers.pending_approval, lab_agents.backend,
mcp_servers, blog_tokens.token_hash, …). See CHANGELOG 0.12.2.

These tests pin the two invariants that prevent silent recurrence:

1. main.py.run_database_migrations stamps `0001_baseline` on first run,
   never `head`. The init.sql snapshot is treated as the 0001-era schema
   regardless of what columns it happens to contain.
2. After the conftest fixture sets up the test DB (init.sql + stamp 0001 +
   upgrade head), every column/table referenced in the bug report exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text


def test_main_py_stamps_baseline_not_head() -> None:
    """The bug was a literal `stamp head` — guard against re-introduction."""
    main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
    src = main_py.read_text()
    assert 'command.stamp, cfg, "0001_baseline"' in src, (
        "run_database_migrations must stamp 0001_baseline on first run"
    )
    assert 'command.stamp, cfg, "head"' not in src, (
        "stamping head on fresh DB is the 0.11.0 bug — see CHANGELOG 0.12.2"
    )


def test_main_py_self_heals_broken_stamp() -> None:
    """0.11.0–0.12.1 deployments shipped with alembic_version=head but the
    schema missing migration 0005+. 0.12.2 must detect this state and
    re-stamp to 0001_baseline so the catch-up migrations replay."""
    main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
    src = main_py.read_text()
    # The detection probe must look for a column from 0005+ (the earliest
    # missing one in the bug report).
    assert "pending_approval" in src, (
        "self-heal must probe for ai_providers.pending_approval (migration 0005) "
        "to detect the 0.11.0-0.12.1 broken-stamp state"
    )
    assert "broken_stamp" in src or "broken-stamp" in src, (
        "self-heal branch must be present — see CHANGELOG 0.12.2 recovery section"
    )


@pytest.mark.asyncio
async def test_fresh_install_schema_has_all_migrated_columns(db) -> None:
    """Every column the 0.12.1 user-bug logs flagged as missing must exist
    after init.sql + Alembic catch-up. The conftest fixture already runs
    that bootstrap, so this is just an assertion on the final state."""
    checks = [
        ("ai_providers", "pending_approval"),  # 0005
        ("blog_tokens", "token_hash"),  # 0006
        ("access_tokens", "token_hash"),  # 0006
        ("library_agents", "backend"),  # 0013
        ("lab_agents", "backend"),  # 0013
    ]
    for table, column in checks:
        result = await db.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": column},
        )
        assert result.scalar() == 1, f"missing column {table}.{column} — init.sql drift bug"

    mcp_exists = (
        await db.execute(text("SELECT to_regclass('public.mcp_servers') IS NOT NULL"))
    ).scalar()
    assert mcp_exists, "mcp_servers table missing — migration 0012 did not run"

    head = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert head == "0015_orchestrator_model_default", f"alembic not at head: {head}"
