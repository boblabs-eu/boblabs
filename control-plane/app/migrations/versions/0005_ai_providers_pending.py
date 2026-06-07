"""Add pending_approval column to ai_providers.

Cluster I — every agent metrics tick was free to CREATE new AIProvider
rows with is_active=True; a peer who knows the global AGENT_SECRET could
inject providers pointing at attacker-controlled base_urls and the
control-plane would dispatch LLM calls (and decrypted api_keys) there.
This revision gates new auto-discovered rows behind admin approval.

  - ``pending_approval`` defaults to TRUE on the column so new rows
    inserted by ``_sync_*`` arrive un-approved.
  - Existing rows are backfilled to ``FALSE`` so currently-trusted
    providers keep serving traffic without operator action.
  - The engine resolver filters ``WHERE pending_approval = FALSE`` so
    pending rows are invisible to dispatch until approved.

Idempotent via ``IF NOT EXISTS``.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0005_ai_providers_pending"
down_revision: Union[str, None] = "0004_workflows_acl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1 — add the column with TRUE default so new INSERTs (sync code
    # paths) start as pending.
    op.execute(
        "ALTER TABLE public.ai_providers "
        "ADD COLUMN IF NOT EXISTS pending_approval boolean NOT NULL DEFAULT true"
    )
    # Step 2 — grandfather existing rows. They were trusted before this
    # commit; flipping every row to pending would break operators on
    # upgrade. New rows continue to inherit the column default = true.
    op.execute(
        "UPDATE public.ai_providers SET pending_approval = false "
        "WHERE pending_approval = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_providers_pending "
        "ON public.ai_providers (pending_approval) "
        "WHERE pending_approval = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_ai_providers_pending")
    op.execute("ALTER TABLE public.ai_providers DROP COLUMN IF EXISTS pending_approval")
