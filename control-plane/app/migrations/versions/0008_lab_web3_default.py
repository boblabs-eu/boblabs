"""D02 + D07 — lab_web3_access.id DEFAULT + drop duplicate llm_events indexes.

D02: lab_web3_access.id was created `uuid NOT NULL` with no
     DEFAULT, so raw-SQL inserts (no ORM-side default fill) failed
     with "null value in column id". The ORM has `default=uuid.uuid4`
     so SQLAlchemy paths work; raw paths do not.

D07: init.sql created two indexes on llm_events.request_id — one
     hand-written (`idx_llm_events_request_id`) and one from
     SQLAlchemy's auto-create (`ix_llm_events_request_id`). Drop the
     auto-create copy; the hand-written name is referenced elsewhere.

Operator action: none.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0008_lab_web3_default"
down_revision: Union[str, None] = "0007_portfolio_snapshots_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # D02 — make raw-SQL INSERTs work.
    op.execute(
        "ALTER TABLE public.lab_web3_access "
        "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )
    # D07 — drop the duplicate ix_ index. The idx_ one stays.
    op.execute("DROP INDEX IF EXISTS public.ix_llm_events_request_id")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.lab_web3_access "
        "ALTER COLUMN id DROP DEFAULT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_events_request_id "
        "ON public.llm_events (request_id)"
    )
