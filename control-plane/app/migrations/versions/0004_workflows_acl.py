"""Add acl column to workflows.

Cluster F — workflows previously had no per-resource ACL. The router
gated only by ``require_infra_access`` so any infra-whitelisted user
could execute any workflow against any server, and ``workflows.project_id``
SET NULL on project delete made workflows survive without any parent ACL.

This revision:
  - Adds ``workflows.acl JSONB NOT NULL`` with the standard
    ``{"owner":"admin","editors":[],"viewers":[]}`` default.
  - Backfills the owner from each workflow's parent project where one
    exists (so existing project-scoped workflows keep their effective
    ownership). Workflows with no project stay admin-owned.
  - Adds a GIN index ``idx_workflows_acl`` matching the pattern used by
    projects/labs/rag_collections/wallets/conversations/resources.

Idempotent via ``IF NOT EXISTS`` so fresh installs (which already have
the column from a future init.sql update) and re-runs are no-ops.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004_workflows_acl"
down_revision: Union[str, None] = "0003_is_public"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_ACL = '{"owner": "admin", "editors": [], "viewers": []}'


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE public.workflows "
        f"ADD COLUMN IF NOT EXISTS acl JSONB NOT NULL DEFAULT '{_DEFAULT_ACL}'::jsonb"
    )
    # Backfill from parent project's acl.owner where available. Wrapped in
    # PL/pgSQL so the JSON path operators are explicit and the update is
    # safe to re-run.
    op.execute(
        """
        DO $$
        BEGIN
            UPDATE public.workflows w
            SET acl = jsonb_set(
                w.acl,
                '{owner}',
                COALESCE(p.acl -> 'owner', '"admin"'::jsonb),
                true
            )
            FROM public.projects p
            WHERE w.project_id = p.id
              AND p.acl IS NOT NULL
              AND (w.acl ->> 'owner') = 'admin';
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflows_acl ON public.workflows USING gin (acl)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_workflows_acl")
    op.execute("ALTER TABLE public.workflows DROP COLUMN IF EXISTS acl")
