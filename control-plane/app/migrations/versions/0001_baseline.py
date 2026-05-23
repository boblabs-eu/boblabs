"""baseline — represents the schema as defined by control-plane/app/migrations/init.sql.

This revision is empty: existing prod DBs are stamped to this revision (or to head),
and fresh installs get the schema from init.sql via Postgres docker-entrypoint-initdb.d.
Real DDL changes start from 0002.
"""

from typing import Sequence, Union


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
