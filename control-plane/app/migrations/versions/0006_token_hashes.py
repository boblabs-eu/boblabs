"""Hash bearer tokens at rest (cluster K, partial).

  - ``access_tokens.token_hash`` (SHA-256 hex of the plaintext token).
  - ``blog_tokens.token_hash`` (same).

The plaintext ``token`` columns are kept for the duration of a
deprecation window so existing tokens continue to validate (the repo
layer uses dual-read — try hash first, fall back to plaintext compare).
A follow-up migration drops the plaintext columns once an operator has
rotated all in-flight tokens.

Operator action: nothing required immediately. ``alembic upgrade``
populates the new columns from the existing plaintext rows so all
tokens keep working. New issuances populate ``token_hash`` only.

Out of scope for this revision:
  - ``ai_providers.api_key`` Fernet-encrypt-at-rest (needs a key-mgmt
    decision: env var KEK vs KMS).
  - ``consumer_apps.secret`` Fernet-encrypt-at-rest (HMAC verify needs
    the plaintext, so encryption is the only path — same key-mgmt
    decision).
  - ``servers.agent_token`` field already exists but is unused by the
    runtime (AGENT_SECRET is a global env var); skipping until the
    per-server token surface is wired.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0006_token_hashes"
down_revision: Union[str, None] = "0005_ai_providers_pending"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.access_tokens "
        "ADD COLUMN IF NOT EXISTS token_hash varchar(64)"
    )
    op.execute(
        "ALTER TABLE public.blog_tokens "
        "ADD COLUMN IF NOT EXISTS token_hash varchar(64)"
    )
    # Backfill existing rows so the new lookup path works immediately
    # for tokens that were issued before this commit.
    op.execute(
        "UPDATE public.access_tokens "
        "SET token_hash = encode(digest(token, 'sha256'), 'hex') "
        "WHERE token_hash IS NULL AND token IS NOT NULL"
    )
    op.execute(
        "UPDATE public.blog_tokens "
        "SET token_hash = encode(digest(token, 'sha256'), 'hex') "
        "WHERE token_hash IS NULL AND token IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_tokens_token_hash "
        "ON public.access_tokens (token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_blog_tokens_token_hash "
        "ON public.blog_tokens (token_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_blog_tokens_token_hash")
    op.execute("DROP INDEX IF EXISTS public.idx_access_tokens_token_hash")
    op.execute("ALTER TABLE public.blog_tokens DROP COLUMN IF EXISTS token_hash")
    op.execute("ALTER TABLE public.access_tokens DROP COLUMN IF EXISTS token_hash")
