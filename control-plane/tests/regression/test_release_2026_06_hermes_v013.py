"""Regression invariants for the 0.13.0 Hermes release.

Pins three things that the 0.13.0 commits added or fixed:

1. Migration ``0016_hermes_activated`` is idempotent (``IF NOT EXISTS``
   on both ALTER TABLE statements) — required for re-runs against a
   partially-migrated DB.
2. ORM ``Mapped[bool]`` for ``hermes_activated`` declares
   ``server_default="false"`` on BOTH ``LibraryAgent`` and ``LabAgent``.
   This is the invariant the ``feedback_migration_schema_audit``
   memory captures: any migration that adds a column with a server
   default MUST be matched in the ``Mapped[...]`` annotation, or the
   ORM and Pydantic response models diverge from the actual table.
3. The hermes-adapter's ``_persist_model_config`` writes
   ``provider: custom`` (the ``5c418ef`` fix), not ``provider: openai``.
   Hermes' ``PROVIDER_REGISTRY`` has no ``openai`` entry; native cron
   jobs raised ``Unknown provider 'openai'`` on every run before this
   fix landed.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_migration_0016_uses_if_not_exists() -> None:
    """0016_hermes_activated must be idempotent on re-run."""
    mig = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "migrations"
        / "versions"
        / "0016_hermes_activated.py"
    )
    src = mig.read_text()
    assert src.count("ADD COLUMN IF NOT EXISTS hermes_activated") == 2, (
        "0016_hermes_activated must guard both ALTER TABLE statements with "
        "IF NOT EXISTS — operators sometimes re-run a partial migration and "
        "a plain ADD COLUMN would raise."
    )
    assert src.count("DROP COLUMN IF EXISTS hermes_activated") == 2, (
        "downgrade() must mirror the same idempotency"
    )


def test_orm_hermes_activated_has_server_default_false() -> None:
    """Both ORM models declare server_default='false' for the new column.

    Why this matters: the migration adds the column with
    ``DEFAULT false``. If the ``Mapped[...]`` lacks ``server_default``,
    SQLAlchemy treats existing rows as if the column had no DB-level
    default — which silently breaks Pydantic response models and
    reflective metadata checks. See feedback_migration_schema_audit.
    """
    models = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "models"
        / "orchestrator.py"
    )
    src = models.read_text()
    # Both LibraryAgent and LabAgent must carry the Mapped[bool] + server_default.
    assert (
        src.count('hermes_activated: Mapped[bool] = mapped_column(') == 2
    ), "both LibraryAgent and LabAgent must declare hermes_activated"
    # We can't easily disambiguate the two Mapped blocks at the text level, but
    # the migration default is server_default="false" — count occurrences
    # against the Mapped declarations.
    assert src.count('server_default="false"') >= 2, (
        "both hermes_activated Mapped columns must carry server_default=\"false\" "
        "so the ORM matches what migration 0016 wrote into the DB."
    )


def test_hermes_adapter_persists_custom_provider_not_openai() -> None:
    """The 5c418ef fix must stay in place.

    Persisting ``provider: openai`` into ~/.hermes/config.yaml made every
    autonomous cron run raise ``Unknown provider 'openai'`` because Hermes'
    PROVIDER_REGISTRY only knows ``openai-api`` / ``openai-codex`` (no
    bare ``openai``). The fix persists ``custom`` instead, which makes
    Hermes' resolve_runtime_provider trust the gateway base_url and
    rebuild the same chat_completions runtime as interactive turns.
    """
    candidates = [
        Path(__file__).resolve().parents[3] / "hermes-adapter" / "adapter" / "main.py",
        Path("/repo/hermes-adapter/adapter/main.py"),
        Path("/workspace/hermes-adapter/adapter/main.py"),
    ]
    adapter = next((p for p in candidates if p.exists()), None)
    if adapter is None:
        pytest.skip("hermes-adapter/adapter/main.py not on disk in this runner")
    src = adapter.read_text()
    assert 'm["provider"] = conn.get("provider") or "custom"' in src, (
        "_persist_model_config must fall back to provider='custom', not 'openai'. "
        "See CHANGELOG 0.13.0 — Fixed."
    )
    # And make sure we don't slip back into the broken pattern.
    assert 'm["provider"] = "openai"' not in src, (
        "do not hardcode provider='openai' — Hermes' PROVIDER_REGISTRY has no "
        "'openai' entry, autonomous cron runs would raise on every tick."
    )
