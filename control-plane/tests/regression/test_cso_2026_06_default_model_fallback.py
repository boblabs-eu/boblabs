"""Regression: lab dispatcher must auto-fall-back when the default model
is stale, instead of 422'ing.

0.12.0-0.12.2 init.sql hardcoded `orchestrator_settings.orchestrator_model
DEFAULT 'qwen2.5:72b'`. The dispatcher refused to run any lab whose
default didn't match a registered model — making fresh installs unable
to run anything until the operator manually set + saved a model. 0.12.3:

1. Migration 0015 drops the bogus column DEFAULT.
2. Dispatcher (`labs_execution.py` + `library_agents.py`) falls back to
   the first registered model with a logger.warning when the configured
   default is missing or stale. Only 422's when no models exist at all.

These tests pin both invariants statically (no live request — keeps
the test self-contained and fast).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text


def test_migration_0015_present() -> None:
    """The 0015 migration must exist and target the right column."""
    mig = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "migrations"
        / "versions"
        / "0015_orchestrator_model_default.py"
    )
    assert mig.exists(), "migration 0015 missing — see CHANGELOG 0.12.3"
    src = mig.read_text()
    assert "DROP DEFAULT" in src, "0015 must DROP the column default"
    assert "qwen2.5:72b" in src, "0015 must null out singleton rows still on the bogus default"


def test_init_sql_no_longer_hardcodes_qwen_default() -> None:
    """init.sql must not declare DEFAULT 'qwen2.5:72b' on orchestrator_model."""
    init_sql = Path(__file__).resolve().parents[2] / "app" / "migrations" / "init.sql"
    src = init_sql.read_text()
    assert "DEFAULT 'qwen2.5:72b'" not in src, (
        "init.sql still hardcodes the phantom default — see CHANGELOG 0.12.3"
    )


def test_labs_execution_falls_back_to_first_model() -> None:
    """labs_execution.py must not 422 when default is stale and models exist."""
    src = (
        Path(__file__).resolve().parents[2] / "app" / "api" / "routes" / "labs_execution.py"
    ).read_text()
    # Old behavior had: raise HTTPException(422, "...no default model set")
    # New behavior must log a warning + use all_models[0] as fallback.
    assert "all_models[0]" in src, "labs_execution.py must fall back to first available model"
    assert "does not match any registered model" in src, (
        "labs_execution.py must log a warning when falling back"
    )
    assert "No models are registered" in src, (
        "labs_execution.py must keep a true 422 for the no-models-at-all case"
    )


def test_library_agents_falls_back_to_first_model() -> None:
    """library_agents.py must mirror the labs_execution.py fallback."""
    src = (
        Path(__file__).resolve().parents[2] / "app" / "api" / "routes" / "library_agents.py"
    ).read_text()
    assert "all_models[0]" in src, "library_agents.py must fall back to first available model"
    assert "does not match any registered model" in src, (
        "library_agents.py must log a warning when falling back"
    )
    assert "No models are registered" in src, (
        "library_agents.py must keep a true 422 for the no-models-at-all case"
    )


@pytest.mark.asyncio
async def test_orchestrator_settings_default_is_null_after_init(db) -> None:
    """After conftest bootstrap, the singleton orchestrator_settings row's
    orchestrator_model column must be NULL — the 0015 migration cleared it."""
    val = (
        await db.execute(text("SELECT orchestrator_model FROM orchestrator_settings WHERE id=1"))
    ).scalar()
    assert val is None, (
        f"orchestrator_settings.orchestrator_model should be NULL on fresh install; got {val!r}"
    )


@pytest.mark.asyncio
async def test_settings_endpoint_serves_200_with_null_orchestrator_model(
    anonymous_client, db
) -> None:
    """GET /api/v1/orchestrator/settings must return 200 (not 500) when
    orchestrator_model is NULL — the post-0.12.3 state. 0.12.3 shipped
    migration 0015 that nulled the column but left the Pydantic
    response schema declaring it as a non-nullable `str`, which caused
    `ResponseValidationError → 500`. 0.12.4: `str | None = None`."""
    # Conftest already left orchestrator_model NULL (0015 effect). Force
    # NULL again here to be robust against any later mutation in the
    # session.
    await db.execute(text("UPDATE orchestrator_settings SET orchestrator_model=NULL WHERE id=1"))
    await db.commit()

    res = await anonymous_client.get("/api/v1/orchestrator/settings")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["orchestrator_model"] is None, body
    # Sanity: other fields still serialize correctly.
    assert "orchestrator_provider" in body
    assert "max_concurrent_tasks" in body
