"""Widen secret columns to fit Fernet ciphertext (CSO #4).

``ai_providers.api_key`` and ``mcp_servers.auth_token`` are now
encrypted at rest under ``KEY_ENCRYPTION_SECRET`` via
``app.services.crypto.EncryptedString``. Fernet ciphertext is
~1.3x the plaintext + ~100 bytes overhead — widen the columns so a
realistic-length OpenAI key (~100 chars) or MCP bearer (~2000 chars)
still fits after encryption.

Migration does **not** re-encrypt existing rows — they keep their
plaintext until the operator runs ``python -m app.scripts.encrypt_secrets``
once. The column type is bidirectional during the rollout window
(plaintext is detected by the absence of the Fernet ``gAAAAA`` prefix
and returned as-is).

Downgrade narrows the columns back. Any encrypted rows that exceed the
old length would error on the ``ALTER TYPE`` — operator is expected to
decrypt-in-place first if rolling back, which is a deliberate footgun:
losing this column type silently would leak.

Idempotent — re-running is safe.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0014_secret_at_rest"
down_revision: Union[str, None] = "0013_agent_backend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.ai_providers ALTER COLUMN api_key TYPE varchar(2000)")
    op.execute("ALTER TABLE public.mcp_servers ALTER COLUMN auth_token TYPE varchar(4000)")


def downgrade() -> None:
    op.execute("ALTER TABLE public.ai_providers ALTER COLUMN api_key TYPE varchar(500)")
    op.execute("ALTER TABLE public.mcp_servers ALTER COLUMN auth_token TYPE varchar(2000)")
