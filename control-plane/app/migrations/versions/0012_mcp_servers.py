"""Add mcp_servers table.

MCP (Model Context Protocol) client support — a standalone registry of
external MCP servers (Stripe, data.gouv, Hermes, …) whose tools are exposed
to agents under namespaced ``mcp__<slug>__<tool>`` names.

Deliberately NOT tied to ``servers`` (no server_id) and NOT gated by
``pending_approval`` — the operator is the only thing that creates these
rows, so an explicit ``enabled`` flag (default false) is the control.

Idempotent via ``IF NOT EXISTS``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012_mcp_servers"
down_revision: Union[str, None] = "0011_trading_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.mcp_servers (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name          varchar(255) NOT NULL UNIQUE,
            slug          varchar(64)  NOT NULL UNIQUE,
            transport     varchar(20)  NOT NULL DEFAULT 'http',
            url           varchar(1000),
            headers       jsonb        NOT NULL DEFAULT '{}'::jsonb,
            auth_token    varchar(2000),
            command       varchar(500),
            args          jsonb        NOT NULL DEFAULT '[]'::jsonb,
            env           jsonb        NOT NULL DEFAULT '{}'::jsonb,
            enabled       boolean      NOT NULL DEFAULT false,
            source        varchar(20)  NOT NULL DEFAULT 'custom',
            catalog_key   varchar(64),
            last_seen_at  timestamptz,
            created_at    timestamptz  NOT NULL DEFAULT now(),
            updated_at    timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_servers_enabled "
        "ON public.mcp_servers (enabled) WHERE enabled = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_mcp_servers_enabled")
    op.execute("DROP TABLE IF EXISTS public.mcp_servers")
