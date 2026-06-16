"""Bob Manager — Lab Dispatcher.

Model-aware load-balancing dispatcher for lab LLM calls.

When multiple providers host the same model (e.g. mistral:latest on Server A
and Server B), the dispatcher:
 1. Finds ALL available providers for that model identifier.
 2. Picks the least-loaded provider (fewest queued waiters on its semaphore).
 3. Acquires a per-provider semaphore (concurrency=1 for Ollama, configurable).
 4. If the chosen provider errors, retries on the next available provider.

When all providers are busy, requests queue automatically on the semaphore
and are served FIFO as slots free up.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient

from app.models.orchestrator import AIModel, AIProvider, Lab, LabAgent, LlmEvent
from app.models.server import Server
from app.services.llm_provider import LLMProvider, create_provider

logger = logging.getLogger(__name__)


async def _log_llm_event(db: AsyncSession, **kwargs) -> None:
    """Fire-and-forget insert of an LLM event row.

    Uses an independent session so commits don't affect the caller's
    transaction.  Sets created_at explicitly for distinct timestamps.
    """
    from datetime import datetime, timezone

    from app.database import async_session

    try:
        kwargs.setdefault("created_at", datetime.now(timezone.utc))
        async with async_session() as log_db:
            ev = LlmEvent(**kwargs)
            log_db.add(ev)
            await log_db.commit()
    except Exception as e:
        logger.debug("Failed to log LLM event: %s", e)


def _strip_images(messages: list[dict]) -> list[dict]:
    """Return a lightweight copy of messages with base64 images replaced by placeholders."""
    stripped = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"[base64 image ~{len(url) // 1024}KB]"},
                            }
                        )
                    else:
                        parts.append(part)
                else:
                    parts.append(part)
            stripped.append({**msg, "content": parts})
        else:
            stripped.append(msg)
    return stripped


# Max concurrent LLM requests per provider (Ollama processes one at a time)
_DEFAULT_CONCURRENCY = 1

# Global slot registry: shared across all dispatchers / labs
# so concurrent labs serialize access to the same providers.
_global_slots: dict[UUID, "_ProviderSlot"] = {}
_global_lock = asyncio.Lock()

# Caller affinity: (lab_id, caller_name) → provider_id
# Keeps the same agent/orchestrator on the same server across calls
# so Ollama doesn't unload/reload the KV cache.
_caller_affinity: dict[tuple[UUID, str], UUID] = {}


def clear_lab_affinity(lab_id: UUID) -> None:
    """Remove all affinity entries for a lab (called when lab stops/completes)."""
    keys_to_remove = [k for k in _caller_affinity if k[0] == lab_id]
    for k in keys_to_remove:
        del _caller_affinity[k]


class _ProviderSlot:
    """Cached provider with a concurrency semaphore."""

    __slots__ = ("llm", "provider", "semaphore", "_waiters")

    def __init__(self, llm: LLMProvider, provider: AIProvider, concurrency: int):
        self.llm = llm
        self.provider = provider
        self.semaphore = asyncio.Semaphore(concurrency)
        self._waiters = 0

    @property
    def queue_depth(self) -> int:
        """How many coroutines are waiting + active on this provider."""
        return self._waiters

    async def acquire(self):
        self._waiters += 1
        await self.semaphore.acquire()

    def release(self):
        self._waiters -= 1
        self.semaphore.release()


class LabDispatcher:
    """Model-aware load-balancing dispatcher for lab LLM calls."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_slot(self, provider_id: UUID) -> _ProviderSlot:
        """Get or create a provider slot with semaphore (global singleton)."""
        if provider_id in _global_slots:
            return _global_slots[provider_id]

        async with _global_lock:
            # Double-check after acquiring lock
            if provider_id in _global_slots:
                return _global_slots[provider_id]

            # Cluster I — also gate on pending_approval=False so an
            # un-approved auto-discovered provider can't receive dispatch.
            result = await self.db.execute(
                select(AIProvider).where(
                    AIProvider.id == provider_id,
                    AIProvider.is_active == True,
                    AIProvider.pending_approval == False,
                )
            )
            prov = result.scalars().first()
            if prov is None:
                raise RuntimeError(
                    f"AI provider {provider_id} not found, inactive, or pending admin approval."
                )

            # Detach from session so cached instance won't try lazy refreshes
            self.db.expunge(prov)
            make_transient(prov)

            from app.services.pipelines import is_media_pipeline

            if is_media_pipeline(prov.provider_type):
                raise RuntimeError(
                    f"Provider '{prov.name}' is a media pipeline ({prov.provider_type}), not an LLM. "
                    f"It cannot be used in Labs."
                )

            llm = create_provider(prov.provider_type, prov.base_url, prov.api_key)
            # Ollama: serial (1), vLLM/OpenAI: can handle more concurrent requests
            concurrency = _DEFAULT_CONCURRENCY
            if prov.provider_type in ("openai", "vllm", "huggingface"):
                concurrency = 4
            elif prov.provider_type == "claude_cli":
                # One `claude -p` subprocess per request; the wrapper's own
                # semaphore (CLAUDE_CLI_CONCURRENCY, default 2) is the hard cap.
                concurrency = 2
            slot = _ProviderSlot(llm, prov, concurrency)
            _global_slots[provider_id] = slot
            return slot

    async def _find_all_providers_for_model(
        self, model_identifier: str
    ) -> list[tuple[AIModel, _ProviderSlot]]:
        """Find ALL available providers hosting the given model, sorted by load."""
        result = await self.db.execute(
            select(AIModel).where(
                AIModel.model_identifier == model_identifier,
                AIModel.is_available == True,
            )
        )
        model_rows = result.scalars().all()
        if not model_rows:
            raise RuntimeError(f"No available provider hosts model '{model_identifier}'.")

        candidates = []
        for mr in model_rows:
            try:
                slot = await self._get_slot(mr.provider_id)
                candidates.append((mr, slot))
            except RuntimeError:
                continue  # provider inactive, skip

        if not candidates:
            raise RuntimeError(f"No active provider for model '{model_identifier}'.")

        # Sort by queue depth (least loaded first)
        candidates.sort(key=lambda c: c[1].queue_depth)
        return candidates

    def _sort_with_affinity(
        self,
        candidates: list[tuple[AIModel, _ProviderSlot]],
        lab_id: UUID | None,
        caller_name: str,
    ) -> list[tuple[AIModel, _ProviderSlot]]:
        """Re-order candidates to prefer caller's affinity provider and spread callers.

        Priority:
        1. Caller's own affinity provider (keep KV cache warm)
        2. Providers not pinned by other callers in the same lab (spread load)
        3. Least queue depth (original tiebreaker)
        """
        if not lab_id:
            return candidates

        affinity_key = (lab_id, caller_name)
        pinned_provider_id = _caller_affinity.get(affinity_key)

        # Collect provider IDs pinned by OTHER callers in this lab
        other_pinned: set[UUID] = set()
        for (lid, cname), pid in _caller_affinity.items():
            if lid == lab_id and cname != caller_name:
                other_pinned.add(pid)

        def sort_key(pair: tuple[AIModel, _ProviderSlot]) -> tuple[int, int]:
            pid = pair[1].provider.id
            # Tier 0: caller's own affinity provider (best — KV cache warm)
            if pinned_provider_id and pid == pinned_provider_id:
                return (0, pair[1].queue_depth)
            # Tier 1: providers NOT used by other callers (spread across servers)
            if pid not in other_pinned:
                return (1, pair[1].queue_depth)
            # Tier 2: providers already pinned by other callers (worst — causes cache thrash)
            return (2, pair[1].queue_depth)

        return sorted(candidates, key=sort_key)

    async def _get_model_identifier(self, model_id: UUID) -> str:
        """Resolve a model UUID to its model_identifier string.

        Does NOT filter by is_available — the caller (call_with_loadbalance)
        finds all *available* providers for the same identifier across all
        servers.  Filtering here would fail when the lab's saved model_id
        points to a server that went offline, even though others host it.
        """
        result = await self.db.execute(select(AIModel).where(AIModel.id == model_id))
        model_row = result.scalars().first()
        if model_row is None:
            raise RuntimeError(f"AI model {model_id} not found.")
        return model_row.model_identifier

    async def _call_with_loadbalance(
        self,
        model_identifier: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        caller_name: str,
        caller_type: str = "lab_agent",
        lab_id: UUID | None = None,
        conversation_id: UUID | None = None,
        tools: list[dict] | None = None,
        think: bool | str | None = None,
    ) -> dict:
        """Route an LLM call across all providers hosting the model.

        Uses caller affinity to keep the same agent/orchestrator on the same
        server (preserves Ollama KV cache), and spreads different callers
        across different servers.  Falls back to least-loaded on failure.
        """
        # Block media pipelines (e.g. riffusion) — they are not LLMs
        from app.services.pipelines import is_media_pipeline

        result = await self.db.execute(
            select(AIModel).where(
                AIModel.model_identifier == model_identifier,
                AIModel.is_available == True,
            )
        )
        first_model = result.scalars().first()
        if first_model:
            prov_result = await self.db.execute(
                select(AIProvider).where(AIProvider.id == first_model.provider_id)
            )
            prov = prov_result.scalars().first()
            if prov and is_media_pipeline(prov.provider_type):
                raise RuntimeError(
                    f"'{model_identifier}' is a {prov.provider_type} media pipeline, not an LLM. "
                    f"It cannot be used as an orchestrator or agent model in Labs."
                )

        candidates = await self._find_all_providers_for_model(model_identifier)
        candidates = self._sort_with_affinity(candidates, lab_id, caller_name)
        max_attempts = len(candidates)
        req_id = uuid.uuid4()  # Shared across all events for this request

        # Log queue event
        await _log_llm_event(
            self.db,
            request_id=req_id,
            event_type="queue",
            model_identifier=model_identifier,
            caller_type=caller_type,
            caller_name=caller_name,
            lab_id=lab_id,
            conversation_id=conversation_id,
            max_attempts=max_attempts,
        )

        last_error = None
        tried: set[UUID] = set()

        for idx, (_model_row, slot) in enumerate(candidates, 1):
            if slot.provider.id in tried:
                continue
            tried.add(slot.provider.id)

            logger.info(
                "%s: queuing on provider '%s' (queue_depth=%d) for model '%s'",
                caller_name,
                slot.provider.name,
                slot.queue_depth,
                model_identifier,
            )

            # Resolve server name for logging (provider name may be model name for HuggingFace)
            server_name = slot.provider.name  # fallback
            if slot.provider.server_id:
                sr = await self.db.execute(
                    select(Server).where(Server.id == slot.provider.server_id)
                )
                srv = sr.scalars().first()
                if srv:
                    server_name = srv.name

            # Log dispatch event
            await _log_llm_event(
                self.db,
                request_id=req_id,
                event_type="dispatch",
                model_identifier=model_identifier,
                provider_name=slot.provider.name,
                server_name=server_name,
                caller_type=caller_type,
                caller_name=caller_name,
                lab_id=lab_id,
                conversation_id=conversation_id,
                attempt=idx,
                max_attempts=max_attempts,
                input_messages=_strip_images(messages),
            )

            await slot.acquire()
            try:
                t0 = time.monotonic()
                result = await slot.llm.chat(
                    messages=messages,
                    model=model_identifier,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    think=think,
                )
                duration_ms = int((time.monotonic() - t0) * 1000)

                logger.info(
                    "%s: model=%s provider=%s tokens_in=%s tokens_out=%s duration=%dms",
                    caller_name,
                    model_identifier,
                    slot.provider.name,
                    result.get("tokens_in"),
                    result.get("tokens_out"),
                    duration_ms,
                )

                # Log response event
                await _log_llm_event(
                    self.db,
                    request_id=req_id,
                    event_type="response",
                    model_identifier=model_identifier,
                    provider_name=slot.provider.name,
                    server_name=server_name,
                    caller_type=caller_type,
                    caller_name=caller_name,
                    lab_id=lab_id,
                    conversation_id=conversation_id,
                    tokens_in=result.get("tokens_in"),
                    tokens_out=result.get("tokens_out"),
                    duration_ms=duration_ms,
                    attempt=idx,
                    max_attempts=max_attempts,
                    output_content=result.get("content"),
                )

                # Record affinity: pin this caller to this provider
                if lab_id:
                    _caller_affinity[(lab_id, caller_name)] = slot.provider.id

                return {
                    **result,
                    "provider": slot.provider.name,
                    "duration_ms": duration_ms,
                }
            except Exception as e:
                logger.warning(
                    "%s: provider '%s' failed for model '%s': %s — trying next",
                    caller_name,
                    slot.provider.name,
                    model_identifier,
                    e,
                )
                last_error = e

                # Log failed event
                await _log_llm_event(
                    self.db,
                    request_id=req_id,
                    event_type="failed",
                    model_identifier=model_identifier,
                    provider_name=slot.provider.name,
                    server_name=server_name,
                    caller_type=caller_type,
                    caller_name=caller_name,
                    lab_id=lab_id,
                    conversation_id=conversation_id,
                    attempt=idx,
                    max_attempts=max_attempts,
                    error=str(e),
                )
            finally:
                slot.release()

        raise RuntimeError(
            f"{caller_name}: all providers failed for model '{model_identifier}'. "
            f"Last error: {last_error}"
        )

    # ── Public API ───────────────────────────────

    async def call_orchestrator(
        self,
        lab: Lab,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """Call the orchestrator LLM with load balancing.

        Returns {"content": str, "tokens_in": int, "tokens_out": int,
                 "model": str, "provider": str, "duration_ms": int,
                 "tool_calls": [...]}.
        """
        if lab.orchestrator_model_id is None:
            # Fall back to system-wide default model
            from app.repositories.orchestrator_repo import OrchestratorSettingsRepository

            settings_repo = OrchestratorSettingsRepository(self.db)
            settings = await settings_repo.get()
            if not settings or not settings.orchestrator_model:
                raise RuntimeError("Lab has no orchestrator_model_id and no default model set.")
            model_identifier = settings.orchestrator_model
        else:
            model_identifier = await self._get_model_identifier(lab.orchestrator_model_id)
        return await self._call_with_loadbalance(
            model_identifier=model_identifier,
            messages=messages,
            temperature=float(lab.orchestrator_temperature),
            max_tokens=lab.orchestrator_max_tokens,
            caller_name="Orchestrator",
            caller_type="lab_orchestrator",
            lab_id=lab.id,
            tools=tools,
        )

    async def is_claude_agent(self, agent: LabAgent) -> bool:
        """True when the agent's brain is a full-capacity claude-agent:* model.

        Such an agent runs Claude Code with its OWN tools + multi-turn inside the
        claude-cli wrapper; the caller delegates the whole task and takes the final
        text (no Bob Lab tool loop), exactly like the Hermes path.
        """
        if getattr(agent, "model_id", None) is None:
            return False
        try:
            ident = await self._get_model_identifier(agent.model_id)
        except Exception:
            return False
        return ident.startswith("claude-agent:")

    async def call_agent(
        self,
        agent: LabAgent,
        messages: list[dict],
        lab_id: UUID | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Call the LLM assigned to a lab agent with load balancing.

        Returns same dict shape as call_orchestrator.  When native tool
        calling is triggered the result includes a 'tool_calls' key.
        """
        if agent.model_id is None:
            raise RuntimeError(f"Lab agent '{agent.name}' has no model_id configured.")

        model_identifier = await self._get_model_identifier(agent.model_id)
        return await self._call_with_loadbalance(
            model_identifier=model_identifier,
            messages=messages,
            temperature=float(agent.temperature),
            max_tokens=agent.max_tokens,
            caller_name=f"Agent '{agent.name}'",
            caller_type="lab_agent",
            lab_id=lab_id,
            tools=tools,
        )
