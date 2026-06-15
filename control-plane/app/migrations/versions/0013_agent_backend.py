"""Add backend column to library_agents and lab_agents.

Hermes external-agent-backend support — a per-agent discriminator:
``'native'`` (default, Bob Lab drives the LLM loop) vs ``'hermes'`` (the
turn is delegated to a per-agent Hermes container running its own loop;
``model_id`` keeps its meaning as the LLM Hermes uses).

Existing rows backfill to 'native' via the column default — zero behavior
change for current agents.

Idempotent via ``IF NOT EXISTS``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_agent_backend"
down_revision: Union[str, None] = "0012_mcp_servers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.library_agents "
        "ADD COLUMN IF NOT EXISTS backend varchar(20) NOT NULL DEFAULT 'native'"
    )
    op.execute(
        "ALTER TABLE public.lab_agents "
        "ADD COLUMN IF NOT EXISTS backend varchar(20) NOT NULL DEFAULT 'native'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.lab_agents DROP COLUMN IF EXISTS backend")
    op.execute("ALTER TABLE public.library_agents DROP COLUMN IF EXISTS backend")
