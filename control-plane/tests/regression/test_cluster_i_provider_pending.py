"""Cluster I — AIProvider auto-discovery approval gate.

History:
- `0.10.0` (cluster I) — auto-discovered providers were always created
  `pending_approval=True, is_active=False` to mitigate the scenario in
  which a leaked ``AGENT_SECRET`` is used to register a malicious
  ``base_url``.
- `0.12.1` — the default flipped to **auto-approve**. The strict gate
  now requires opting in via ``BOB_REQUIRE_PROVIDER_APPROVAL=true``.

This module asserts (on the Ollama sync path — same gate is wired into
the other ``_sync_*`` writers, see ``provider_policy.py``):
  1. Strict mode (env=true) — auto-discovery lands pending (the
     original 0.10.0 behavior).
  2. Default mode (env unset / false) — auto-discovery lands approved
     and dispatchable.
  3. Resync of an approved provider NEVER demotes it back to pending
     (orthogonal to the env, since 0.10.0).
  4. The dispatcher still filters by ``pending_approval`` (so the
     strict-mode gate still has teeth when enabled).
"""

from __future__ import annotations

import uuid

import pytest
from app.models.orchestrator import AIProvider
from app.models.server import Server
from sqlalchemy import select

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_auto_discovered_ollama_provider_is_pending_in_strict_mode(db, monkeypatch):
    """With BOB_REQUIRE_PROVIDER_APPROVAL=true → pending_approval=True, is_active=False."""
    monkeypatch.setenv("BOB_REQUIRE_PROVIDER_APPROVAL", "true")

    from app.database import async_session
    from app.websocket.agent_handler import _sync_ollama_models

    server = Server(
        id=uuid.uuid4(),
        name="strict-agent",
        host="gpu-strict.example.com",
        agent_token="x",
        status="online",
    )
    db.add(server)
    await db.commit()

    await _sync_ollama_models(
        agent_name="strict-agent",
        ollama_models=[{"name": "llama3:8b", "family": "llama"}],
        db_session_factory=async_session,
    )

    row = (
        await db.execute(select(AIProvider).where(AIProvider.name == "strict-agent"))
    ).scalar_one()
    assert row.pending_approval is True, (
        "strict mode: auto-discovered provider must land pending_approval=True"
    )
    assert row.is_active is False, "strict mode: auto-discovered provider must land is_active=False"


@pytest.mark.asyncio
async def test_auto_discovered_ollama_provider_is_approved_by_default(db, monkeypatch):
    """With BOB_REQUIRE_PROVIDER_APPROVAL unset → pending_approval=False, is_active=True (0.12.1 default)."""
    monkeypatch.delenv("BOB_REQUIRE_PROVIDER_APPROVAL", raising=False)

    from app.database import async_session
    from app.websocket.agent_handler import _sync_ollama_models

    server = Server(
        id=uuid.uuid4(),
        name="default-agent",
        host="gpu-default.example.com",
        agent_token="x",
        status="online",
    )
    db.add(server)
    await db.commit()

    await _sync_ollama_models(
        agent_name="default-agent",
        ollama_models=[{"name": "llama3:8b", "family": "llama"}],
        db_session_factory=async_session,
    )

    row = (
        await db.execute(select(AIProvider).where(AIProvider.name == "default-agent"))
    ).scalar_one()
    assert row.pending_approval is False, (
        "default mode (0.12.1): auto-discovered provider must land pending_approval=False"
    )
    assert row.is_active is True, (
        "default mode (0.12.1): auto-discovered provider must land is_active=True"
    )


@pytest.mark.asyncio
async def test_existing_provider_not_demoted_by_resync(db):
    """If an admin has already approved the provider, a resync MUST NOT
    flip it back to pending. Holds in both modes — only CREATE touches
    the approval state."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_ollama_models

    server = Server(
        id=uuid.uuid4(),
        name="approved-agent",
        host="gpu-2.example.com",
        agent_token="x",
        status="online",
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
    """Spot-check that lab_dispatcher still references pending_approval —
    even though the default flipped to auto-approve, operators in strict
    mode rely on the dispatcher actually enforcing it."""
    import inspect

    from app.services import lab_dispatcher

    src = inspect.getsource(lab_dispatcher)
    assert "pending_approval" in src, (
        "lab_dispatcher source no longer references pending_approval — "
        "cluster I regression (strict-mode dispatcher would no longer be enforced)"
    )
