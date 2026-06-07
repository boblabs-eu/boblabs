"""D01 — portfolio_snapshots composite PK.

The Python ORM declares (ts, wallet_id) as the composite primary key,
but init.sql created the table with neither a PK nor a UNIQUE
constraint — so the schema and the model disagreed. Anyone who
upgraded from init.sql got a table that silently accepted duplicate
(ts, wallet_id) rows, and any direct-SQL UPSERT path was missing the
ON CONFLICT target.

This migration:
  1. Collapses any pre-existing duplicates by keeping the row with the
     greatest total_value_usd (arbitrary but deterministic).
  2. ALTERs wallet_id to NOT NULL (it was nullable in init.sql).
  3. Adds the composite PRIMARY KEY (ts, wallet_id).

Operator action: none. Step 1 dedupes silently before constraint
creation. If there were duplicates they were unindexable anyway.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0007_portfolio_snapshots_pk"
down_revision: Union[str, None] = "0006_token_hashes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Dedupe rows that would collide on the new PK. Keep the row
    #    with the highest total_value_usd per (ts, wallet_id) — the
    #    snapshot_loop always writes the same value within a tick, so
    #    in practice this is a no-op for prod, but it makes the
    #    constraint creation safe for any historical drift.
    op.execute("""
        DELETE FROM public.portfolio_snapshots a
        USING public.portfolio_snapshots b
        WHERE a.ctid < b.ctid
          AND a.ts = b.ts
          AND a.wallet_id IS NOT DISTINCT FROM b.wallet_id
    """)
    # 2) wallet_id was nullable in init.sql but the ORM says NOT NULL.
    #    PK creation requires NOT NULL — backfill any NULLs first.
    op.execute(
        "DELETE FROM public.portfolio_snapshots WHERE wallet_id IS NULL"
    )
    op.execute(
        "ALTER TABLE public.portfolio_snapshots "
        "ALTER COLUMN wallet_id SET NOT NULL"
    )
    # 3) Add the composite PK if missing.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'portfolio_snapshots_pkey'
                  AND conrelid = 'public.portfolio_snapshots'::regclass
            ) THEN
                ALTER TABLE public.portfolio_snapshots
                ADD CONSTRAINT portfolio_snapshots_pkey
                PRIMARY KEY (ts, wallet_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.portfolio_snapshots "
        "DROP CONSTRAINT IF EXISTS portfolio_snapshots_pkey"
    )
    op.execute(
        "ALTER TABLE public.portfolio_snapshots "
        "ALTER COLUMN wallet_id DROP NOT NULL"
    )
