"""D12 + D04 — UNIQUE on workflow_steps(workflow_id, step_order)
and an ACL JSONB shape CHECK on labs / workflows / conversations.

D12: workflows previously assumed a stable Python sort on step_order
     across duplicate values — undefined behavior. The fix is a
     unique constraint at the DB layer so two steps in the same
     workflow can never share an ordering value.

D04: every table with an `acl` JSONB column relies on the shape
     ``{owner: <string>, editors: [<string>], viewers: [<string>]}``.
     ``filter_query_by_access`` silently excludes rows whose ACL is
     malformed (no `owner` key → no row matches). A DB-level CHECK
     turns that silent skip into an INSERT/UPDATE error so the
     malformed row is rejected at the boundary instead of becoming
     invisible later.

The CHECK allows extra top-level keys (we use ``acl->>'tag'`` to mark
consumer-app / showroom / agent-instance labs), and is null-safe by
gating on ``acl IS NOT NULL``.

Operator action: none, IF every existing ACL row already matches the
shape (the cluster-G + Wave 4 work normalized these). The migration
backfills malformed rows to ``get_default_acl('admin')`` before
adding the constraint so the upgrade can't fail on legacy data.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009_workflow_step_acl_shape"
down_revision: Union[str, None] = "0008_lab_web3_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that carry the canonical ACL JSONB shape.
_ACL_TABLES = ("labs", "workflows", "conversations")


_ACL_CHECK_EXPR = """
    acl IS NULL OR (
        jsonb_typeof(acl) = 'object'
        AND acl ? 'owner'
        AND jsonb_typeof(acl->'owner') = 'string'
        AND (NOT acl ? 'editors' OR jsonb_typeof(acl->'editors') = 'array')
        AND (NOT acl ? 'viewers' OR jsonb_typeof(acl->'viewers') = 'array')
    )
"""


def upgrade() -> None:
    # ── D12: UNIQUE(workflow_id, step_order) ───────────────────────
    # Dedupe any duplicate step_order values inside the same workflow
    # by re-numbering them. We pick the row order by id (deterministic
    # surrogate) so the migration is repeatable.
    op.execute("""
        WITH renumbered AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY workflow_id ORDER BY step_order, id
                   ) AS new_order
            FROM public.workflow_steps
        )
        UPDATE public.workflow_steps ws
        SET step_order = r.new_order
        FROM renumbered r
        WHERE ws.id = r.id
          AND ws.step_order IS DISTINCT FROM r.new_order
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_workflow_step_order'
                  AND conrelid = 'public.workflow_steps'::regclass
            ) THEN
                ALTER TABLE public.workflow_steps
                ADD CONSTRAINT uq_workflow_step_order
                UNIQUE (workflow_id, step_order);
            END IF;
        END $$;
    """)

    # ── D04: ACL JSONB shape CHECK on every relevant table ─────────
    for table in _ACL_TABLES:
        # 1) Backfill malformed rows so the CHECK doesn't reject the
        #    constraint creation. Anything whose ACL doesn't pass the
        #    shape goes to the safe default {owner: 'admin', ...}.
        op.execute(f"""
            UPDATE public.{table}
            SET acl = '{{"owner":"admin","editors":[],"viewers":[]}}'::jsonb
            WHERE acl IS NOT NULL
              AND NOT (
                jsonb_typeof(acl) = 'object'
                AND acl ? 'owner'
                AND jsonb_typeof(acl->'owner') = 'string'
                AND (NOT acl ? 'editors' OR jsonb_typeof(acl->'editors') = 'array')
                AND (NOT acl ? 'viewers' OR jsonb_typeof(acl->'viewers') = 'array')
              )
        """)
        # 2) Add the CHECK constraint, idempotent.
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'ck_{table}_acl_shape'
                      AND conrelid = 'public.{table}'::regclass
                ) THEN
                    ALTER TABLE public.{table}
                    ADD CONSTRAINT ck_{table}_acl_shape
                    CHECK ({_ACL_CHECK_EXPR});
                END IF;
            END $$;
        """)


def downgrade() -> None:
    for table in _ACL_TABLES:
        op.execute(
            f"ALTER TABLE public.{table} "
            f"DROP CONSTRAINT IF EXISTS ck_{table}_acl_shape"
        )
    op.execute(
        "ALTER TABLE public.workflow_steps "
        "DROP CONSTRAINT IF EXISTS uq_workflow_step_order"
    )
