"""Add is_public column to labs + library_agents.

Anonymous /live used to list every lab in the database with no filter.
This revision adds the opt-in visibility flag (default false) so existing
labs become hidden until the owner or an admin flips them via the Share
modal or the new Admin → Labs tab.

Fresh installs already have the column from init.sql; this revision uses
IF NOT EXISTS guards so re-running on a fresh DB is a no-op.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003_is_public"
down_revision: Union[str, None] = "0002_blog_slug"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.labs "
        "ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE public.library_agents "
        "ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.library_agents DROP COLUMN IF EXISTS is_public")
    op.execute("ALTER TABLE public.labs DROP COLUMN IF EXISTS is_public")
