"""Resolve a Bob Lab model_id to a concrete provider connection for Hermes.

The hermes-backed agent's ``model_id`` points at an ``AIModel`` row exactly
like a native agent's — the operator picks it from the same dropdown. Per run
we resolve it to ``{provider_type, base_url, api_key, model_identifier}`` so
the hermes-adapter can point Hermes at that LLM.

Resolution mirrors the dispatcher's semantics
(``lab_dispatcher._get_model_identifier`` + ``_find_all_providers_for_model``):
the saved row's identifier is what matters; if the saved row's own provider is
inactive/offline, fall back to any active provider hosting the same
identifier (so a model served by two Ollama boxes keeps working when one is
down).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import AIModel, AIProvider

logger = logging.getLogger(__name__)


async def resolve_model_identifier(db: AsyncSession, model_id: UUID | None) -> str:
    """Validate the model and return its identifier (gateway mode).

    Same error semantics as :func:`resolve_model_spec`, but the connection
    details stay inside Bob Lab — Hermes is pointed at the internal LLM
    gateway, which load-balances per call across all providers hosting the
    identifier (and logs to the LLM-event feed).
    """
    spec = await resolve_model_spec(db, model_id)
    return spec["model_identifier"]


async def resolve_model_spec(db: AsyncSession, model_id: UUID | None) -> dict:
    """Return {provider_type, base_url, api_key, model_identifier} for a model.

    Raises RuntimeError with an operator-readable message when the model is
    missing or no active provider hosts it.
    """
    if model_id is None:
        raise RuntimeError(
            "Hermes agent has no model selected. Pick the model Hermes should "
            "use in the agent's settings."
        )

    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    saved = result.scalars().first()
    if saved is None:
        raise RuntimeError(f"AI model {model_id} not found.")

    # All available rows sharing the identifier, saved row's provider first.
    result = await db.execute(
        select(AIModel, AIProvider)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(
            AIModel.model_identifier == saved.model_identifier,
            AIModel.is_available.is_(True),
            AIProvider.is_active.is_(True),
            AIProvider.pending_approval.is_(False),
        )
    )
    rows = list(result.all())
    if not rows:
        raise RuntimeError(f"No active provider hosts model '{saved.model_identifier}' for Hermes.")
    rows.sort(key=lambda r: 0 if r[0].provider_id == saved.provider_id else 1)
    model_row, provider = rows[0]

    return {
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "api_key": provider.api_key,
        "model_identifier": model_row.model_identifier,
    }
