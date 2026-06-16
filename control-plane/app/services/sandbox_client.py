"""HMAC-signed HTTP client for per-lab sandbox containers (CSO #8).

Closes the sandbox lateral-movement finding: all per-lab sandboxes
share one Docker network, so an attacker who achieves RCE inside one
sandbox could previously hit any other sandbox at
``http://bob-lab-<other_uuid>:9000/python_exec`` and execute code in
its workspace.

Defense in depth (two locks):
  1. **HMAC signature** on every request from the control-plane —
     sandbox refuses unsigned calls when ``SANDBOX_HMAC_SECRET`` is
     configured. An attacker inside sandbox A has the secret only if
     they can read it from a control-plane process; they cannot pull
     it from sandbox B (different env). And the secret never reaches
     the sandbox over the wire — both sides have it from env.
  2. **Lab-id binding** — sandbox refuses requests whose body
     ``lab_id`` doesn't match its ``SANDBOX_LAB_ID`` env. So even if
     an attacker forwarded a stolen signed request to a different
     sandbox, the target would reject it.

Compat mode: if ``SANDBOX_HMAC_SECRET`` is empty/unset on either side
the deployment falls back to unsigned (current behavior). Lets the
operator roll this out without a flag day.

Header format::

    X-Bob-Sandbox-Auth: t=<unix_ts_seconds>,sig=<hex_hmac_sha256>

HMAC input: ``<unix_ts>.<sha256(body_bytes)>``. The body hash (not the
body itself) keeps the header small; replay is bounded by the 60-second
timestamp window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 60-second window for clock skew + request RTT. Matches the existing
# AGENT_SECRET WS auth window — same threat model, same trade-off.
SIGNATURE_WINDOW_SECONDS = 60

_HEADER_NAME = "X-Bob-Sandbox-Auth"


def _get_secret() -> str:
    """Pull the shared secret from settings at call time."""
    from app.config import settings

    return (settings.sandbox_hmac_secret or "").strip()


def signing_enabled() -> bool:
    return bool(_get_secret())


def compute_signature(secret: str, timestamp: int, body_bytes: bytes) -> str:
    """HMAC-SHA256 over ``<ts>.<sha256_hex(body)>``. Public for the
    sandbox-side verifier and the regression test."""
    body_digest = hashlib.sha256(body_bytes).hexdigest()
    message = f"{timestamp}.{body_digest}".encode("ascii")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_auth_header(secret: str, body_bytes: bytes) -> str:
    """Return the value for ``X-Bob-Sandbox-Auth``."""
    ts = int(time.time())
    sig = compute_signature(secret, ts, body_bytes)
    return f"t={ts},sig={sig}"


async def signed_post(
    sandbox_url: str,
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float = 60.0,
) -> httpx.Response:
    """POST ``payload`` to ``sandbox_url + endpoint`` with HMAC signature.

    Returns the raw ``httpx.Response`` so callers can choose whether to
    ``raise_for_status`` and whether to ``.json()``. (Some sandbox
    endpoints — like ``/python_exec`` — return ``{"success": False, ...}``
    with HTTP 200 on failure, so blanket ``raise_for_status`` would be
    wrong.)

    When ``SANDBOX_HMAC_SECRET`` is unset the call goes through without
    the auth header, matching the pre-fix behavior. The sandbox-side
    middleware mirrors this — unsigned requests pass through when the
    sandbox also has no secret.
    """
    # Serialize once so the signature covers the exact bytes httpx sends.
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"content-type": "application/json"}
    secret = _get_secret()
    if secret:
        headers[_HEADER_NAME] = build_auth_header(secret, body_bytes)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(
            f"{sandbox_url}{endpoint}",
            content=body_bytes,
            headers=headers,
        )


async def signed_post_json(
    sandbox_url: str,
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Convenience: POST + ``.json()`` for the common case."""
    resp = await signed_post(sandbox_url, endpoint, payload, timeout=timeout)
    return resp.json()
