"""CSO Finding #8 — sandbox HMAC + lab_id binding.

Pre-fix: every per-lab sandbox container ran on the shared
``bob-manager_bob-network`` Docker network with no authentication.
Once an attacker had RCE inside any sandbox they could:
  1. Hit any other sandbox at ``http://bob-lab-<other_uuid>:9000/python_exec``
     and run code in that lab's workspace.
  2. Hit their own sandbox with ``lab_id=<other_uuid>`` and read/write
     files from another lab's directory under the shared
     ``lab_resources`` volume.

Post-fix:
  - Control-plane signs every sandbox request with HMAC-SHA256 over
    ``<unix_ts>.<sha256(body)>`` using ``SANDBOX_HMAC_SECRET``.
  - Sandbox middleware rejects unsigned/badly-signed/replayed requests
    (>60s old).
  - Sandbox also rejects bodies whose ``lab_id`` doesn't match its
    ``SANDBOX_LAB_ID`` env (set by ``container_manager.py`` at
    creation time).
  - Both legacy modes preserved when env vars are empty so the rollout
    doesn't require a flag-day.

This test locks the signing primitive (the verifier side is exercised
manually after deploy with the smoke-checks in
``docs/AGENT.md`` — testing FastAPI middleware inline would require
spinning up the sandbox container).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from app.services.sandbox_client import (
    SIGNATURE_WINDOW_SECONDS,
    build_auth_header,
    compute_signature,
    signing_enabled,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# Inside the test container `/app/sandbox/main.py` is NOT mounted (only
# control-plane/ is). Skip the sandbox-side guard if it isn't visible.
_SANDBOX_MAIN_CANDIDATES = [
    REPO_ROOT.parent / "sandbox" / "main.py",
    Path("/sandbox/main.py"),
]
SANDBOX_MAIN = next((p for p in _SANDBOX_MAIN_CANDIDATES if p.is_file()), None)
CONTAINER_MGR = REPO_ROOT / "app" / "services" / "container_manager.py"


# ── Source-introspection guards ──────────────────────────────────────


def test_sandbox_middleware_present() -> None:
    """The sandbox main.py must declare the HMAC middleware."""
    if SANDBOX_MAIN is None:
        pytest.skip(
            "sandbox/main.py not visible from test container — checked from CI/host instead"
        )
    src = SANDBOX_MAIN.read_text(encoding="utf-8")
    assert '@app.middleware("http")' in src, "sandbox must register an http middleware"
    assert "SANDBOX_HMAC_SECRET" in src, "sandbox must read SANDBOX_HMAC_SECRET env"
    assert "SANDBOX_LAB_ID" in src, "sandbox must read SANDBOX_LAB_ID env"
    assert "hmac.compare_digest" in src, "sandbox signature compare must be constant-time"


def test_container_manager_passes_env_vars() -> None:
    src = CONTAINER_MGR.read_text(encoding="utf-8")
    assert "SANDBOX_LAB_ID" in src, "container_manager must pass SANDBOX_LAB_ID"
    assert "SANDBOX_HMAC_SECRET" in src, "container_manager must pass SANDBOX_HMAC_SECRET"
    assert "environment=" in src or "env=" in src, "container_manager must set container env"


def test_tool_call_sites_use_signed_post() -> None:
    """Every sandbox HTTP call site must go through signed_post(_json)."""
    targets = [
        REPO_ROOT / "app" / "services" / "tools" / "tool_exec.py",
        REPO_ROOT / "app" / "services" / "tools" / "tool_db.py",
        REPO_ROOT / "app" / "services" / "tools" / "tool_integrations.py",
        REPO_ROOT / "app" / "services" / "tools" / "tool_web.py",
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        assert "signed_post" in src, f"{path.name} must use signed_post — CSO #8 regression"


# ── HMAC primitive ───────────────────────────────────────────────────


def test_compute_signature_is_deterministic() -> None:
    body = b'{"lab_id": "abc"}'
    a = compute_signature("secret", 1700000000, body)
    b = compute_signature("secret", 1700000000, body)
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_signature_changes_with_body() -> None:
    a = compute_signature("k", 1700000000, b'{"x":1}')
    b = compute_signature("k", 1700000000, b'{"x":2}')
    assert a != b


def test_signature_changes_with_timestamp() -> None:
    a = compute_signature("k", 1700000000, b"{}")
    b = compute_signature("k", 1700000001, b"{}")
    assert a != b


def test_signature_changes_with_secret() -> None:
    a = compute_signature("k1", 1700000000, b"{}")
    b = compute_signature("k2", 1700000000, b"{}")
    assert a != b


def test_build_auth_header_shape() -> None:
    header = build_auth_header("secret", b"{}")
    parts = dict(p.split("=", 1) for p in header.split(","))
    assert "t" in parts and "sig" in parts
    assert int(parts["t"]) > 1_700_000_000  # plausibly recent
    assert len(parts["sig"]) == 64


def test_signature_window_is_60_seconds() -> None:
    """Keep the window tight enough that a leaked sig has minutes-not-hours of
    replay value. Doubles as a CSO doc — surfacing the constant for review."""
    assert SIGNATURE_WINDOW_SECONDS == 60


def test_signing_enabled_reflects_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_hmac_secret", "")
    assert signing_enabled() is False
    monkeypatch.setattr(settings, "sandbox_hmac_secret", "some-secret")
    assert signing_enabled() is True


# ── End-to-end mock: middleware verifier reproduces server logic ────


def _mimic_sandbox_verify(secret: str, header_value: str, body: bytes, now_offset: int = 0) -> bool:
    """A pure-python copy of the sandbox middleware verification —
    exists so we can assert behavior without spinning up the container.
    Tests below should fail in the same way the real sandbox would."""
    import hashlib
    import hmac

    try:
        parts = dict(p.split("=", 1) for p in header_value.split(","))
        ts = int(parts["t"])
        sig = parts["sig"]
    except (KeyError, ValueError):
        return False
    if abs((int(time.time()) + now_offset) - ts) > SIGNATURE_WINDOW_SECONDS:
        return False
    body_digest = hashlib.sha256(body).hexdigest()
    msg = f"{ts}.{body_digest}".encode("ascii")
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def test_valid_signature_verifies() -> None:
    body = json.dumps({"lab_id": "abc", "code": "print(1)"}).encode()
    header = build_auth_header("shared-secret", body)
    assert _mimic_sandbox_verify("shared-secret", header, body)


def test_wrong_secret_fails() -> None:
    body = b'{"lab_id":"x"}'
    header = build_auth_header("client-secret", body)
    assert not _mimic_sandbox_verify("server-secret", header, body)


def test_tampered_body_fails() -> None:
    body = b'{"lab_id":"x"}'
    header = build_auth_header("k", body)
    tampered = b'{"lab_id":"y"}'
    assert not _mimic_sandbox_verify("k", header, tampered)


def test_expired_timestamp_fails() -> None:
    body = b"{}"
    # Build header as if "now" is 120s in the future, then verify with real now.
    sig = compute_signature("k", int(time.time()) - 120, body)
    header = f"t={int(time.time()) - 120},sig={sig}"
    assert not _mimic_sandbox_verify("k", header, body)


def test_missing_header_fails() -> None:
    assert not _mimic_sandbox_verify("k", "", b"{}")
    assert not _mimic_sandbox_verify("k", "garbage", b"{}")
