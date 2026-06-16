"""Auto-discovered provider approval policy.

When an agent self-reports a provider (Ollama, Claude CLI, vLLM,
ComfyUI, etc.) via the metrics tick, the control plane writes a new
`AIProvider` row. Whether that row is immediately dispatchable or
gated behind an admin approval flow is controlled by the
``BOB_REQUIRE_PROVIDER_APPROVAL`` environment variable.

History:
- `0.10.0` (cluster I) — auto-discovered providers were always created
  with ``pending_approval=True, is_active=False`` to mitigate a
  ``AGENT_SECRET``-leak scenario where an attacker could register a
  malicious ``base_url`` and serve LLM traffic. The gate was correct
  but had **zero UI surface and zero docs**, so every fresh installer
  hit a silent dead end where models existed in the DB but the
  dispatcher refused them.
- `0.12.1` — the default flipped to **auto-approve on discovery**.
  Operators who want the original strict gate set
  ``BOB_REQUIRE_PROVIDER_APPROVAL=true`` in the control plane's
  environment.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def provider_requires_approval() -> bool:
    """Return True if auto-discovered providers must wait for admin approval.

    Default: False. Auto-discovered providers land
    ``is_active=True, pending_approval=False`` (dispatchable immediately).

    Set ``BOB_REQUIRE_PROVIDER_APPROVAL=true`` to restore the 0.10.0
    strict gate. Newly-discovered providers then land
    ``is_active=False, pending_approval=True`` and an admin must
    approve them via ``POST /api/v1/orchestrator/providers/{id}/approve``
    (or the inline button in the orchestrator console).
    """
    return os.environ.get("BOB_REQUIRE_PROVIDER_APPROVAL", "").strip().lower() in _TRUTHY
