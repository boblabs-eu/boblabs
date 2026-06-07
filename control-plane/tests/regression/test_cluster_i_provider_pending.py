"""Cluster I — AIProvider auto-discovery defaults to pending+inactive.

Pre-fix: when an agent self-reported its base_url via `_sync_*`, the
new AIProvider row was created `is_active=True` and immediately
dispatchable. An attacker who obtained `AGENT_SECRET` could register a
provider at any URL and serve LLM traffic.

Post-fix: every `_sync_*` writer sets `pending_approval=True,
is_active=False`. The engine resolver excludes unapproved providers.
Migration 0005 grandfathered existing rows to `pending_approval=False`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.orchestrator import AIProvider
from app.models.server import Server

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_auto_discovered_ollama_provider_is_pending(db):
    """Simulate _sync_ollama_models for a fresh agent → row is pending+inactive."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_ollama_models

    server = Server(
        id=uuid.uuid4(),
        name="test-agent",
        host="gpu-1.example.com",
        agent_token="x",
        status="online",
    )
    db.add(server)
    await db.commit()

    await _sync_ollama_models(
        agent_name="test-agent",
        ollama_models=[{"name": "llama3:8b", "family": "llama"}],
        db_session_factory=async_session,
    )

    row = (await db.execute(
        select(AIProvider).where(AIProvider.name == "test-agent")
    )).scalar_one()
    assert row.pending_approval is True, (
        "auto-discovered provider must default to pending_approval=True — cluster I regression"
    )
    assert row.is_active is False, (
        "auto-discovered provider must default to is_active=False — cluster I regression"
    )


@pytest.mark.asyncio
async def test_existing_provider_not_demoted_by_resync(db):
    """If an admin has already approved the provider, a resync MUST NOT
    flip it back to pending. The fix only sets pending on CREATE."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_ollama_models

    server = Server(
        id=uuid.uuid4(), name="approved-agent",
        host="gpu-2.example.com", agent_token="x", status="online",
    )
    db.add(server)
    await db.commit()
    pre_approved = AIProvider(
        id=uuid.uuid4(),
        name="approved-agent",
        provider_type="ollama",
        base_url="http://gpu-2.example.com:11434",
        server_id=server.id,
        is_active=True,
        pending_approval=False,
    )
    db.add(pre_approved)
    await db.commit()

    await _sync_ollama_models(
        agent_name="approved-agent",
        ollama_models=[{"name": "qwen2.5:32b"}],
        db_session_factory=async_session,
    )

    await db.refresh(pre_approved)
    assert pre_approved.pending_approval is False, (
        "approved provider was flipped back to pending — cluster I regression"
    )
    assert pre_approved.is_active is True


@pytest.mark.asyncio
async def test_dispatcher_filters_pending_providers(db):
    """Spot-check that lab_dispatcher excludes pending_approval rows."""
    import inspect
    from app.services import lab_dispatcher

    src = inspect.getsource(lab_dispatcher)
    assert "pending_approval" in src, (
        "lab_dispatcher source no longer references pending_approval — "
        "cluster I regression (dispatcher may route to unapproved providers)"
    )
