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
    resources: list[dict] | None = None,
    timeout_sec: int | None = None,
) -> dict:
    """Run one Hermes agent turn. Returns the adapter's result dict:

    ``{"content": str, "usage": {"tokens_in", "tokens_out"}, "steps": [...], "outputs": [...]}``
    (usage/steps/outputs optional per contract — normalized to safe defaults here).
    ``resources`` are operator-attached input files (``{name, content_b64}``) the
    adapter materializes inside the agent's container; ``outputs`` are files the
    agent produced.
    """
    payload = {
        "system_prompt": system_prompt or "",
        "instruction": instruction,
        "model": model,
        "history": history or [],
        "options": options or {},
        "resources": resources or [],
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
        "outputs": data.get("outputs") or [],
        "cron_jobs": int(data.get("cron_jobs") or 0),
    }


async def cron_tick(base_url: str) -> bool:
    """Fire the agent's native cron scheduler once — Bob is the external 60 s
    heartbeat the scheduler expects. Fire-and-forget (the adapter runs jobs in a
    background thread); returns True if the trigger was accepted."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{base_url}/v1/cron/tick",
                headers={"Authorization": f"Bearer {settings.agent_secret}"},
            )
            return r.status_code < 400
    except httpx.HTTPError as exc:
        logger.debug("cron tick to %s failed: %s", base_url, exc)
        return False


async def cron_output(base_url: str, since: float = 0.0) -> dict:
    """Fetch cron job outputs written since ``since`` (epoch seconds). Returns the
    adapter's ``{"outputs": [{job_id, file, mtime, content}], "now": float}`` —
    or empty/echoed-cursor on failure (so the caller never advances past unread output)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{base_url}/v1/cron/output",
                params={"since": since},
                headers={"Authorization": f"Bearer {settings.agent_secret}"},
            )
            if r.status_code >= 400:
                return {"outputs": [], "now": since}
            data = r.json()
            return data if isinstance(data, dict) else {"outputs": [], "now": since}
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("cron output from %s failed: %s", base_url, exc)
        return {"outputs": [], "now": since}


async def hermes_health(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url}/health")
            return r.status_code == 200
    except Exception:
        return False
