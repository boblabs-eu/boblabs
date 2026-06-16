"""One-shot re-encryption of plaintext secret columns (CSO #4).

Run once **after** setting ``KEY_ENCRYPTION_SECRET`` in the env and
re-deploying bob-api. The control-plane keeps reading plaintext rows
during the rollout window thanks to the bidirectional ``EncryptedString``
column type; this script flips every legacy plaintext row to its Fernet-
encrypted form so backups, replicas, and audit dumps stop leaking.

Usage::

    docker compose exec bob-api python -m app.scripts.encrypt_secrets

Idempotent: rows that are already Fernet ciphertext are skipped. Safe to
re-run if the script is interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.database import async_session
from app.services.crypto import encrypt_secret, encryption_enabled, is_encrypted
from sqlalchemy import text

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


_TARGETS: list[tuple[str, str, str]] = [
    # (table, column, where_pk)
    ("ai_providers", "api_key", "id"),
    ("mcp_servers", "auth_token", "id"),
]


async def _encrypt_table(session, table: str, column: str, pk_col: str) -> tuple[int, int]:
    """Re-encrypt every plaintext row in (table, column). Returns (touched, skipped)."""
    # Read raw on-disk values so we can tell plaintext from ciphertext.
    rows = (
        await session.execute(
            text(f"SELECT {pk_col}, {column} FROM {table} WHERE {column} IS NOT NULL")
        )
    ).all()
    touched, skipped = 0, 0
    for pk, value in rows:
        if value == "" or value is None:
            skipped += 1
            continue
        if is_encrypted(value):
            skipped += 1
            continue
        ciphertext = encrypt_secret(value)
        await session.execute(
            text(f"UPDATE {table} SET {column} = :v WHERE {pk_col} = :pk"),
            {"v": ciphertext, "pk": pk},
        )
        touched += 1
    await session.commit()
    return touched, skipped


async def main() -> int:
    if not encryption_enabled():
        logger.error(
            "KEY_ENCRYPTION_SECRET is not set. Set it in the env first, "
            "redeploy bob-api, then re-run this script."
        )
        return 1

    async with async_session() as session:
        for table, column, pk in _TARGETS:
            touched, skipped = await _encrypt_table(session, table, column, pk)
            logger.info("%s.%s: %d rewritten, %d skipped", table, column, touched, skipped)

        # Sanity check — verify nothing left plaintext.
        for table, column, _ in _TARGETS:
            sample = (
                (
                    await session.execute(
                        text(
                            f"SELECT {column} FROM {table} "
                            f"WHERE {column} IS NOT NULL AND {column} != ''"
                        )
                    )
                )
                .scalars()
                .all()
            )
            bad = [s for s in sample if not is_encrypted(s)]
            if bad:
                logger.error(
                    "Sanity check failed: %d %s.%s rows still plaintext", len(bad), table, column
                )
                return 2

    logger.info("All target rows encrypted on disk.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
