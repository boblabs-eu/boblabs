"""Seed reusable agent templates (OpenClaw, Hermes, ...) on startup.

Reads JSON files from ``/app/templates/agent_templates/*.agent.json`` (bind-mounted
from the repo's ``templates/agent_templates/`` directory) and upserts them as rows
in ``library_agents``.

Idempotent semantics:
- New name → insert.
- Existing name AND row was never edited by the user (``updated_at`` ≈ ``created_at``)
  → refresh fields from JSON (lets us improve preset prompts via repo updates).
- Existing name AND user modified it (``updated_at`` clearly after ``created_at``)
  → leave alone.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.orchestrator import LibraryAgent
from app.repositories.lab_repo import LibraryAgentRepository

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("/app/templates/agent_templates")

# Fields copied verbatim from the JSON file into the LibraryAgent row.
_ALLOWED_FIELDS = {
    "name",
    "role",
    "system_prompt",
    "backend",
    "temperature",
    "max_tokens",
    "tools",
    "tool_set_ids",
    "share_memory",
    "callable_agents",
    "cron_expression",
    "cron_instruction",
    "anti_loop_enabled",
}

# How close updated_at must be to created_at to treat the row as "untouched"
_UNTOUCHED_THRESHOLD = timedelta(seconds=5)


def _filter_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k in _ALLOWED_FIELDS}


async def seed_agent_templates(session_factory: async_sessionmaker) -> dict[str, int]:
    """Seed/refresh agent template presets. Returns counts: created/updated/skipped."""
    counts = {"created": 0, "updated": 0, "skipped": 0}

    if not TEMPLATES_DIR.is_dir():
        logger.info("agent_template_seed: %s missing, skipping", TEMPLATES_DIR)
        return counts

    files = sorted(TEMPLATES_DIR.glob("*.agent.json"))
    if not files:
        logger.info("agent_template_seed: no *.agent.json files in %s", TEMPLATES_DIR)
        return counts

    async with session_factory() as db:
        repo = LibraryAgentRepository(db)
        for path in files:
            try:
                with path.open(encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception as exc:
                logger.warning("agent_template_seed: failed to parse %s: %s", path.name, exc)
                continue

            name = payload.get("name")
            if not name or not isinstance(name, str):
                logger.warning("agent_template_seed: %s has no 'name'", path.name)
                continue

            fields = _filter_fields(payload)

            existing = (
                (await db.execute(select(LibraryAgent).where(LibraryAgent.name == name)))
                .scalars()
                .first()
            )

            if existing is None:
                await repo.create(**fields)
                counts["created"] += 1
                logger.info("agent_template_seed: created %r", name)
                continue

            # Detect user edits
            untouched = (
                existing.updated_at is not None
                and existing.created_at is not None
                and (existing.updated_at - existing.created_at) <= _UNTOUCHED_THRESHOLD
            )
            if not untouched:
                counts["skipped"] += 1
                logger.info("agent_template_seed: skipped %r (user-modified)", name)
                continue

            await repo.update(existing.id, **{k: v for k, v in fields.items() if k != "name"})
            # Re-pin updated_at to created_at so this row stays "untouched" for
            # the next startup. Use raw SQL to bypass SQLAlchemy's onupdate hook
            # which otherwise rewrites updated_at to NOW() on any ORM update.
            await db.execute(
                text("UPDATE library_agents SET updated_at = created_at WHERE id = :id"),
                {"id": existing.id},
            )
            counts["updated"] += 1
            logger.info("agent_template_seed: refreshed %r", name)

        await db.commit()

    logger.info(
        "agent_template_seed: done — created=%d updated=%d skipped=%d",
        counts["created"],
        counts["updated"],
        counts["skipped"],
    )
    return counts
