"""Add hermes_activated column to library_agents and lab_agents.

Native-Hermes-cron support: a durable "this agent's container should stay
running" flag. Set true automatically when a Hermes agent has cron jobs (so its
container stays always-on for the scheduler to tick), and by the explicit
Activate/Deactivate controls. Survives bob-api restarts, so the scheduler's
reconcile step can bring activated containers back up after a restart.

Existing rows backfill to false via the column default — zero behavior change
for current agents.

Idempotent via ``IF NOT EXISTS``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_hermes_activated"
down_revision: Union[str, None] = "0015_orchestrator_model_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.library_agents "
        "ADD COLUMN IF NOT EXISTS hermes_activated boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE public.lab_agents "
        "ADD COLUMN IF NOT EXISTS hermes_activated boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.lab_agents DROP COLUMN IF EXISTS hermes_activated")
    op.execute("ALTER TABLE public.library_agents DROP COLUMN IF EXISTS hermes_activated")
