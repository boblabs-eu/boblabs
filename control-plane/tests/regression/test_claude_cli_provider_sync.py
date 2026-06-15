"""Claude CLI provider sync — auto-discovery via agent metrics.

The per-server claude-cli wrapper (claude-cli/ at the repo root) is
reported by the agent as `claude_cli_models` (+ `claude_cli_port`) in
agent.metrics; `_sync_claude_cli_models` mirrors the Ollama/GPU-service
sync path: provider `claude_cli-<agent>` created pending+inactive
(Cluster I), models upserted with their namespaced `claude-cli:<id>`
identifiers, stale models marked unavailable, resync never demotes an
approved provider, and the provider name never collides with the Ollama
provider (which uses the bare agent name).
"""

from __future__ import annotations

import uuid

import pytest
from app.models.orchestrator import AIModel, AIProvider
from app.models.server import Server
from sqlalchemy import select

pytestmark = pytest.mark.regression


def _models_payload() -> list[dict]:
    """Shape produced by agent/app/collectors/claude_cli.py."""
    return [
        {
            "name": f"claude-cli:{alias}",
            "model": f"claude-cli:{alias}",
            "size": 0,
            "parameter_size": "",
            "quantization": "",
            "family": "claude",
            "format": "claude-cli",
            "modified_at": "",
        }
        for alias in ("haiku", "opus", "sonnet")
    ]


async def _make_server(db, name: str, host: str) -> Server:
    server = Server(
        id=uuid.uuid4(),
        name=name,
        host=host,
        agent_token="x",
        status="online",
    )
    db.add(server)
    await db.commit()
    return server


@pytest.mark.asyncio
async def test_auto_discovered_claude_cli_provider_is_pending(db):
    """Fresh agent → claude_cli-<agent> created pending+inactive with the
    reported port in base_url, models upserted with namespaced ids."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_claude_cli_models

    await _make_server(db, "cli-agent", "gpu-9.example.com")

    await _sync_claude_cli_models(
        agent_name="cli-agent",
        models=_models_payload(),
        port=3099,
        db_session_factory=async_session,
    )

    row = (
        await db.execute(select(AIProvider).where(AIProvider.name == "claude_cli-cli-agent"))
    ).scalar_one()
    assert row.provider_type == "claude_cli"
    assert row.pending_approval is True, (
        "auto-discovered claude_cli provider must default to pending_approval=True"
    )
    assert row.is_active is False
    assert row.base_url == "http://gpu-9.example.com:3099", (
        "base_url must honor the agent-reported wrapper port"
    )

    models = (
        (await db.execute(select(AIModel).where(AIModel.provider_id == row.id))).scalars().all()
    )
    idents = sorted(m.model_identifier for m in models)
    assert idents == ["claude-cli:haiku", "claude-cli:opus", "claude-cli:sonnet"], (
        "model identifiers must keep the claude-cli: namespace (UI tag + "
        "no merge with Anthropic API models in /models/unique)"
    )
    by_ident = {m.model_identifier: m for m in models}
    assert by_ident["claude-cli:opus"].name == "opus (Claude CLI)"
    assert all(m.is_available for m in models)


@pytest.mark.asyncio
async def test_claude_cli_resync_does_not_demote_approved_provider(db):
    """An admin-approved provider must survive a resync; base_url follows
    a port change."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_claude_cli_models

    server = await _make_server(db, "approved-cli-agent", "gpu-10.example.com")
    pre_approved = AIProvider(
        id=uuid.uuid4(),
        name="claude_cli-approved-cli-agent",
        provider_type="claude_cli",
        base_url="http://gpu-10.example.com:3021",
        server_id=server.id,
        is_active=True,
        pending_approval=False,
    )
    db.add(pre_approved)
    await db.commit()

    await _sync_claude_cli_models(
        agent_name="approved-cli-agent",
        models=_models_payload(),
        port=3050,
        db_session_factory=async_session,
    )

    await db.refresh(pre_approved)
    assert pre_approved.pending_approval is False, (
        "approved claude_cli provider was flipped back to pending"
    )
    assert pre_approved.is_active is True
    assert pre_approved.base_url == "http://gpu-10.example.com:3050", (
        "base_url must follow the reported wrapper port on resync"
    )


@pytest.mark.asyncio
async def test_claude_cli_stale_models_marked_unavailable(db):
    """A model removed from CLAUDE_CLI_MODELS disappears from discovery →
    flipped is_available=False on the next sync."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_claude_cli_models

    await _make_server(db, "stale-cli-agent", "gpu-11.example.com")

    await _sync_claude_cli_models(
        agent_name="stale-cli-agent",
        models=_models_payload(),
        port=3021,
        db_session_factory=async_session,
    )
    # Operator pins a single model in .env; aliases drop out.
    await _sync_claude_cli_models(
        agent_name="stale-cli-agent",
        models=[
            {
                "name": "claude-cli:claude-opus-4-8",
                "model": "claude-cli:claude-opus-4-8",
                "family": "claude",
                "format": "claude-cli",
            }
        ],
        port=3021,
        db_session_factory=async_session,
    )

    row = (
        await db.execute(select(AIProvider).where(AIProvider.name == "claude_cli-stale-cli-agent"))
    ).scalar_one()
    models = (
        (await db.execute(select(AIModel).where(AIModel.provider_id == row.id))).scalars().all()
    )
    available = sorted(m.model_identifier for m in models if m.is_available)
    stale = sorted(m.model_identifier for m in models if not m.is_available)
    assert available == ["claude-cli:claude-opus-4-8"]
    assert stale == ["claude-cli:haiku", "claude-cli:opus", "claude-cli:sonnet"]


@pytest.mark.asyncio
async def test_claude_cli_provider_coexists_with_ollama_provider(db):
    """The Ollama provider uses the bare agent name; the claude_cli
    provider must use a distinct name so both can exist for one server
    (AIProvider.name is unique)."""
    from app.database import async_session
    from app.websocket.agent_handler import _sync_claude_cli_models, _sync_ollama_models

    await _make_server(db, "both-agent", "gpu-12.example.com")

    await _sync_ollama_models(
        agent_name="both-agent",
        ollama_models=[{"name": "llama3:8b", "family": "llama"}],
        db_session_factory=async_session,
    )
    await _sync_claude_cli_models(
        agent_name="both-agent",
        models=_models_payload(),
        port=3021,
        db_session_factory=async_session,
    )

    names = sorted(
        (
            await db.execute(
                select(AIProvider.name).where(
                    AIProvider.name.in_(["both-agent", "claude_cli-both-agent"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert names == ["both-agent", "claude_cli-both-agent"]


def test_create_provider_maps_claude_cli_to_openai_compatible():
    """claude_cli reuses the generic OpenAI-dialect client — no custom code."""
    from app.services.llm_provider import OpenAICompatibleProvider, create_provider

    llm = create_provider("claude_cli", "http://gpu-9.example.com:3021", None)
    assert isinstance(llm, OpenAICompatibleProvider)
    assert llm.base_url == "http://gpu-9.example.com:3021"
    assert llm.api_key is None


def test_claude_cli_in_supported_provider_types():
    from app.api.routes.orchestrator import SUPPORTED_PROVIDER_TYPES

    types = {p["type"] for p in SUPPORTED_PROVIDER_TYPES}
    assert "claude_cli" in types
