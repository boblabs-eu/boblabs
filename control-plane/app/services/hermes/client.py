"""HTTP client for the hermes-adapter contract.

Speaks the API defined in ``hermes-adapter/ADAPTER_CONTRACT.md``:

    GET  /health          → 200 when ready
    GET  /v1/info         → {"hermes_version": ..., "tools": [...]}
    POST /v1/agent/run    → run one agent turn, returns the final reply

The ``model`` block is sent with EVERY run so the operator can switch the
underlying LLM from the Bob Lab UI at any time without restarting the
container — the adapter applies it to Hermes per request.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class HermesAdapterError(RuntimeError):
    """A task sent to the Hermes adapter failed or returned an invalid reply."""


async def run_hermes_task(
    base_url: str,
    *,
    system_prompt: str,
    instruction: str,
    model: dict,
    history: list[dict] | None = None,
    options: dict | None = None,
    timeout_sec: int | None = None,
) -> dict:
    """Run one Hermes agent turn. Returns the adapter's result dict:

    ``{"content": str, "usage": {"tokens_in": int, "tokens_out": int}, "steps": [...]}``
    (usage/steps optional per contract — normalized to safe defaults here).
    """
    payload = {
        "system_prompt": system_prompt or "",
        "instruction": instruction,
        "model": model,
        "history": history or [],
        "options": options or {},
    }
    timeout = float(timeout_sec or settings.hermes_default_timeout_sec)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = await client.post(f"{base_url}/v1/agent/run", json=payload)
    except httpx.TimeoutException as exc:
        raise HermesAdapterError(f"Hermes task timed out after {timeout:.0f}s") from exc
    except httpx.HTTPError as exc:
        raise HermesAdapterError(f"Hermes adapter unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise HermesAdapterError(f"Hermes adapter error {resp.status_code}: {resp.text[:500]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise HermesAdapterError("Hermes adapter returned non-JSON response") from exc

    content = data.get("content")
    if not isinstance(content, str):
        raise HermesAdapterError("Hermes adapter reply missing 'content'")

    usage = data.get("usage") or {}
    return {
        "content": content,
        "tokens_in": int(usage.get("tokens_in") or 0),
        "tokens_out": int(usage.get("tokens_out") or 0),
        "steps": data.get("steps") or [],
    }


async def hermes_health(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url}/health")
            return r.status_code == 200
    except Exception:
        return False
