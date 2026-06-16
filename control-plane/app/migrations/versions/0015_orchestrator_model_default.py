"""Drop the 'qwen2.5:72b' default on orchestrator_settings.orchestrator_model.

The hardcoded default landed every fresh install with a phantom default
pointing at a 72B model nobody had. The FE <select> then silently showed
the first available option (looked correct), but the unchanged DB value
caused the lab-execution preflight to 422 with "no default model set".

This migration:
- Drops the column DEFAULT.
- Clears the singleton row's value back to NULL so the lab dispatcher's
  auto-fallback (added in 0.12.3) picks the first registered model.

Idempotent: safe to re-run on partially-patched databases.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0015_orchestrator_model_default"
down_revision: Union[str, None] = "0014_secret_at_rest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.orchestrator_settings ALTER COLUMN orchestrator_model DROP DEFAULT")
    op.execute(
        "UPDATE public.orchestrator_settings SET orchestrator_model=NULL "
        "WHERE orchestrator_model='qwen2.5:72b'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.orchestrator_settings "
        "ALTER COLUMN orchestrator_model SET DEFAULT 'qwen2.5:72b'"
    )
