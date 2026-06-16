"""Fernet encryption-at-rest for sensitive credential columns.

Closes CSO finding #4 (2026-06-09 synthesis report): DB backups, replica
streams, and read-only audit access were all leaking plaintext LLM
provider API keys + MCP auth tokens. Now those columns are encrypted
under ``KEY_ENCRYPTION_SECRET`` (operator-supplied env var); the
database — and any backup, replica, or audit dump derived from it —
only holds Fernet ciphertext.

Design choices
--------------
* **TypeDecorator**, not service-layer encrypt/decrypt. Every call site
  that reads ``provider.api_key`` keeps working unchanged — the column
  type transparently encrypts on bind and decrypts on result. No
  business logic moves into the storage boundary.
* **Opt-in by env var**. If ``KEY_ENCRYPTION_SECRET`` is unset/empty,
  the column behaves as a plain ``String`` (no encryption, no errors).
  Operator can roll this out without a flag-day: set the secret, run
  ``python -m app.scripts.encrypt_secrets``, done.
* **Bidirectional during the rollout window**. Reads detect Fernet
  ciphertext by its ``gAAAAA`` prefix (Fernet version byte 0x80
  url-safe-base64); legacy plaintext rows pass through. After the
  one-shot CLI runs, all rows are encrypted.
* **Key derivation**. The env var is an arbitrary string. We derive a
  32-byte Fernet key by ``urlsafe_b64encode(sha256(secret).digest())``
  — deterministic, never written to disk, in-memory only.

Rotation
--------
Out of scope for v1 — the field is "what key was the last write made
under?" Rotation needs a second key for decrypt-only + a re-encrypt
sweep. Documented as a follow-up.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

# Fernet ciphertext is url-safe-base64 of (version byte || timestamp ||
# iv || ciphertext || hmac). Version 0x80 makes the first byte ``g``
# under standard base64, and the next ~5 chars are predictable. The
# ``gAAAAA`` prefix is the conventional sentinel for "this is a Fernet
# token" — cheap to detect, no false positives in real-world API keys.
_FERNET_PREFIX = "gAAAAA"


def _get_secret() -> str:
    """Pull the encryption secret from settings at call time.

    Imported lazily to avoid a circular import on app startup
    (``settings`` is built during ``app.config`` module load).
    """
    from app.config import settings

    return (settings.key_encryption_secret or "").strip()


def encryption_enabled() -> bool:
    """True iff the operator has configured a non-empty secret."""
    return bool(_get_secret())


def _get_fernet():
    """Build a Fernet instance from the configured secret.

    Returns ``None`` when encryption is disabled (no secret set). The
    caller MUST treat ``None`` as "passthrough" — never encrypt with a
    fallback key, never decrypt by guessing.
    """
    secret = _get_secret()
    if not secret:
        return None
    # cryptography is already pulled in via python-jose[cryptography]
    # in requirements.txt — no new dep.
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def is_encrypted(value: Optional[str]) -> bool:
    """Detect whether a stored value is a Fernet token vs legacy plaintext."""
    return bool(value) and isinstance(value, str) and value.startswith(_FERNET_PREFIX)


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string for storage. None/empty passes through unchanged.

    If encryption is disabled (``KEY_ENCRYPTION_SECRET`` unset), the
    plaintext is returned as-is so the deployment continues to function
    while the operator rolls out key management.
    """
    if plaintext is None or plaintext == "":
        return plaintext
    if is_encrypted(plaintext):
        # Caller already encrypted; don't double-wrap.
        return plaintext
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypt a stored value. Passthrough for legacy plaintext rows.

    Raises ``cryptography.fernet.InvalidToken`` if the row is encrypted
    but the configured secret doesn't match — surfacing key mismatch
    loudly rather than silently corrupting the wallet.
    """
    if value is None or value == "":
        return value
    if not is_encrypted(value):
        # Legacy plaintext (or encryption never enabled). Return as-is.
        return value
    fernet = _get_fernet()
    if fernet is None:
        # Ciphertext on disk but no key in env: operator misconfiguration.
        # Surface loudly — silently returning the ciphertext would hand
        # garbled output to the LLM provider and waste a debug cycle.
        raise RuntimeError(
            "Encrypted secret found in DB but KEY_ENCRYPTION_SECRET is not set. "
            "Set the env var to the same value used when these rows were written."
        )
    return fernet.decrypt(value.encode("ascii")).decode("utf-8")


class EncryptedString(TypeDecorator):
    """A SQLAlchemy String column that's encrypted at rest under Fernet.

    Usage::

        api_key: Mapped[str | None] = mapped_column(
            EncryptedString(2000), nullable=True
        )

    The declared length is the **on-disk** length (the ciphertext is
    ~1.3x the plaintext + 100-byte overhead — size the column for the
    encrypted form, not the plaintext).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D401
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):  # noqa: D401
        return decrypt_secret(value)
