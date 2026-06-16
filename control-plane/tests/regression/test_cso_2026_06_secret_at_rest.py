"""CSO Finding #4 — encryption-at-rest for LLM/MCP credential columns.

Pre-fix: ``ai_providers.api_key`` and ``mcp_servers.auth_token`` were
plaintext columns. A DB backup, replica stream, or read-only audit
dump leaked the operator's full LLM-provider wallet.

Post-fix: both columns use ``EncryptedString`` (Fernet, key derived
from ``KEY_ENCRYPTION_SECRET``). When the env var is set, ORM writes
encrypt before bind and reads decrypt after fetch — call sites stay
unchanged. When unset, behavior is passthrough (deployment compat for
the rollout window). Legacy plaintext rows are detected by the absence
of the ``gAAAAA`` Fernet prefix and read through as-is until the
operator runs ``python -m app.scripts.encrypt_secrets`` once.

This test locks:
  - source shape (models declare ``EncryptedString`` for the two cols)
  - round-trip correctness (encrypt → decrypt = original)
  - passthrough mode (no key set → behaves like plain String)
  - bidirectional read (legacy plaintext + encrypted both decode)
  - mismatched-key error (encrypted row + wrong key → loud failure)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.services.crypto import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_PATH = REPO_ROOT / "app" / "models" / "orchestrator.py"


def _read_models_src() -> str:
    assert MODELS_PATH.is_file(), f"{MODELS_PATH} missing"
    return MODELS_PATH.read_text(encoding="utf-8")


# ── Source-introspection guards ──────────────────────────────────────


def test_models_import_encrypted_string() -> None:
    src = _read_models_src()
    assert "from app.services.crypto import EncryptedString" in src, (
        "orchestrator.py must import EncryptedString — see CSO #4 fix"
    )


def test_ai_providers_api_key_uses_encrypted_string() -> None:
    src = _read_models_src()
    assert "api_key: Mapped[str | None] = mapped_column(EncryptedString" in src, (
        "ai_providers.api_key must be EncryptedString — CSO #4 regression"
    )


def test_mcp_servers_auth_token_uses_encrypted_string() -> None:
    src = _read_models_src()
    assert "auth_token: Mapped[str | None] = mapped_column(EncryptedString" in src, (
        "mcp_servers.auth_token must be EncryptedString — CSO #4 regression"
    )


# ── Round-trip correctness ───────────────────────────────────────────


def test_roundtrip_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "test-key-do-not-use-in-prod")
    plaintext = "sk-test-1234567890abcdef"
    cipher = encrypt_secret(plaintext)
    assert cipher is not None
    assert cipher != plaintext
    assert is_encrypted(cipher), "ciphertext must carry the Fernet prefix"
    assert decrypt_secret(cipher) == plaintext


def test_roundtrip_passthrough_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "")
    plaintext = "sk-test-1234567890abcdef"
    cipher = encrypt_secret(plaintext)
    # No key → encrypt is a no-op so the rollout doesn't break.
    assert cipher == plaintext
    assert decrypt_secret(plaintext) == plaintext


def test_legacy_plaintext_passthrough_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading a legacy plaintext row when encryption IS configured must not error."""
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "test-key")
    # No gAAAAA prefix → treated as legacy plaintext, passed through.
    assert decrypt_secret("sk-legacy-plaintext") == "sk-legacy-plaintext"


def test_mismatched_key_surfaces_loud_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Encrypted row + wrong key must raise, not silently corrupt."""
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "key-A")
    cipher = encrypt_secret("sk-secret")
    monkeypatch.setattr(settings, "key_encryption_secret", "key-B")
    with pytest.raises(Exception):
        decrypt_secret(cipher)


def test_encrypted_row_then_key_unset_surfaces_loud_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator misconfig: ciphertext on disk + KEY_ENCRYPTION_SECRET unset."""
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "key-X")
    cipher = encrypt_secret("sk-secret")
    assert is_encrypted(cipher)
    monkeypatch.setattr(settings, "key_encryption_secret", "")
    with pytest.raises(RuntimeError, match="KEY_ENCRYPTION_SECRET"):
        decrypt_secret(cipher)


def test_empty_and_none_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "test-key")
    assert encrypt_secret(None) is None
    assert encrypt_secret("") == ""
    assert decrypt_secret(None) is None
    assert decrypt_secret("") == ""


def test_double_encrypt_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-encrypting an already-encrypted string is a no-op (CLI safety)."""
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "test-key")
    cipher = encrypt_secret("sk-x")
    cipher2 = encrypt_secret(cipher)
    # Same ciphertext (the helper detected the prefix and didn't wrap again).
    assert cipher == cipher2


# ── Migration presence ──────────────────────────────────────────────


def test_migration_0014_exists() -> None:
    migration = REPO_ROOT / "app" / "migrations" / "versions" / "0014_secret_at_rest.py"
    assert migration.is_file(), (
        f"0014_secret_at_rest.py migration must exist (looked at {migration})"
    )
    src = migration.read_text(encoding="utf-8")
    assert "ai_providers" in src and "api_key" in src
    assert "mcp_servers" in src and "auth_token" in src
