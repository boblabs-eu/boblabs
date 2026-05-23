"""Bob Manager — Consumer-app HMAC auth.

Single source of truth for verifying signed requests on the internal channel.
Every request must carry ``X-App-Id`` plus an HMAC-SHA256 signature over
``<timestamp>.<body>``. The matching HMAC key is looked up in the
``consumer_apps`` table.

The HMAC secret is stored plain in the DB because verifying an HMAC requires
the plain key. Mitigations: admin-only routes, never returned after creation
(except the one-time response on ``POST``), and a future migration to
encrypted-at-rest via KMS / libsodium when we need it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.consumer_app_repo import ConsumerAppRepository

logger = logging.getLogger(__name__)

REPLAY_WINDOW_SEC = 300


def generate_secret() -> str:
    """Return a fresh 64-char hex HMAC secret. 256 bits of entropy."""
    return secrets.token_hex(32)


def _check_timestamp(ts: str) -> None:
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid timestamp")
    if abs(time.time() - ts_int) > REPLAY_WINDOW_SEC:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Stale timestamp")


def _expected_signature(secret: str, ts: str, body: bytes) -> str:
    return hmac.new(
        secret.encode(),
        ts.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()


def _verify_with_secret(secret: str, ts: str, sig: str, body: bytes) -> None:
    expected = _expected_signature(secret, ts, body)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")


async def verify_signed_request(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    app_id: str | None,
    db: AsyncSession,
) -> str:
    """Validate an HMAC-signed internal request. Returns the resolved app_id.

    Raises HTTPException(401) on any auth failure. Unknown / revoked app_ids
    and bad signatures collapse to the same response so callers can't
    enumerate registered slugs.
    """
    if not timestamp or not signature or not app_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing signature")

    _check_timestamp(timestamp)

    repo = ConsumerAppRepository(db)
    record = await repo.get_by_app_id(app_id)
    if record is None or record.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")

    _verify_with_secret(record.secret, timestamp, signature, body)
    try:
        await repo.touch_last_used(record.id)
    except Exception:  # pragma: no cover
        logger.debug("Failed to update last_used_at for %s", app_id)
    return record.app_id
