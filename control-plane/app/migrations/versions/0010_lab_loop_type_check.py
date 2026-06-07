"""O05 — CHECK constraint on labs.loop_type

Pre-fix: ``labs.loop_type`` was a free-form VARCHAR(50). A bad value
(typo, deprecated strategy, mis-translated frontend dropdown) survived
the INSERT and only blew up later when ``get_strategy(loop_type)``
raised ValueError mid-run — leaving the lab stuck in a half-started
state. The CHECK rejects the bad write at the boundary so the API
returns a clean 400 / 500 instead of corrupting the lab row.

Source of truth: ``app.schemas.orchestrator.LoopTypeStr`` (Literal) and
``app.services.loop_strategies.STRATEGY_REGISTRY``. The CHECK below
must include every strategy registered there. Adding a new strategy is
a 3-step change: register class, widen Literal, widen this CHECK
(roll a new migration).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010_lab_loop_type_check"
down_revision: Union[str, None] = "0009_workflow_step_acl_shape"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirror of STRATEGY_REGISTRY keys + LoopTypeStr Literal members.
_VALID_LOOP_TYPES = (
    "plan_execute",
    "critique_refine",
    "round_robin",
    "debate",
    "map_reduce",
    "parallel_broadcast",
    "tree_of_thought",
    "react",
    "supervisor",
    "solo_agent",
)


def upgrade() -> None:
    quoted = ", ".join(f"'{v}'" for v in _VALID_LOOP_TYPES)
    # 1) Backfill any row with an unknown loop_type to the safe default so
    #    the CHECK creation can't fail on legacy data.
    op.execute(f"""
        UPDATE public.labs
        SET loop_type = 'plan_execute'
        WHERE loop_type IS NULL OR loop_type NOT IN ({quoted})
    """)
    # 2) Add the CHECK, idempotent so re-running the migration is safe.
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_labs_loop_type'
                  AND conrelid = 'public.labs'::regclass
            ) THEN
                ALTER TABLE public.labs
                ADD CONSTRAINT ck_labs_loop_type
                CHECK (loop_type IN ({quoted}));
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.labs "
        "DROP CONSTRAINT IF EXISTS ck_labs_loop_type"
    )
