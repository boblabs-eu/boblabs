"""D03 — trading precision: wei-integer amounts + decimals metadata.

Pre-fix: ``trading_positions.amount``, the four ``*_price_usd`` columns,
``trade_history.gas_price_gwei``, and ``trade_history.value_usd`` were
Postgres ``REAL`` / SQLAlchemy ``Float``. Floats round
``Decimal('0.1') + Decimal('0.2')`` to ``0.30000000000000004`` once
they round-trip through the DB — a non-starter for any column an
auditor might later compare against an on-chain log.

This migration migrates each column to a lossless storage shape:

* ``trading_positions.amount``           → ``amount_raw NUMERIC(78, 0)``
  plus a sibling ``token_decimals INTEGER NOT NULL DEFAULT 18`` so
  display code can render the human Decimal via
  ``app.services.trading_units.from_raw``.
* ``trading_positions.{entry,exit,stop_loss,take_profit}_price_usd``
  → ``NUMERIC(38, 18)``.
* ``trade_history.gas_price_gwei`` → ``gas_price_wei NUMERIC(78, 0)``.
  Conversion factor is ``1 gwei = 1e9 wei``.
* ``trade_history.value_usd``      → ``NUMERIC(38, 18)``.
* ``trade_history`` gains ``from_token_decimals`` / ``to_token_decimals``
  ``INTEGER NULL`` so the existing String(78) ``from_amount`` /
  ``to_amount`` columns carry enough metadata for human rendering.

Backfill strategy:

* Existing ``amount`` rows are treated as "human" Decimals (the
  service layer never converted to wei before insert), so the wei
  value is ``amount * 10^token_decimals``. ``token_decimals`` defaults
  to 18 — operators can correct per-row afterwards via UPDATE for
  non-18-decimal tokens.
* ``gas_price_gwei * 1e9`` for the gas rewrite.
* USD-price columns cast verbatim — no scale change, just type
  widening from REAL to NUMERIC(38, 18).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011_trading_precision"
down_revision: Union[str, None] = "0010_lab_loop_type_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── TradingPosition: amount + token_decimals + USD prices ──────

    op.execute("""
        ALTER TABLE public.trading_positions
        ADD COLUMN IF NOT EXISTS token_decimals INTEGER NOT NULL DEFAULT 18
    """)
    op.execute("""
        ALTER TABLE public.trading_positions
        ADD COLUMN IF NOT EXISTS amount_raw NUMERIC(78, 0)
    """)
    # Backfill: existing ``amount`` rows hold human Decimals (the service
    # never wei-converted before insert). Scale up by 10^token_decimals.
    op.execute("""
        UPDATE public.trading_positions
        SET amount_raw = (amount * power(10::numeric, token_decimals))::numeric(78, 0)
        WHERE amount_raw IS NULL
          AND amount IS NOT NULL
    """)
    op.execute("""
        UPDATE public.trading_positions
        SET amount_raw = 0
        WHERE amount_raw IS NULL
    """)
    op.execute("""
        ALTER TABLE public.trading_positions
        ALTER COLUMN amount_raw SET NOT NULL
    """)
    op.execute("ALTER TABLE public.trading_positions DROP COLUMN IF EXISTS amount")

    for col in (
        "entry_price_usd",
        "exit_price_usd",
        "stop_loss_usd",
        "take_profit_usd",
    ):
        op.execute(f"""
            ALTER TABLE public.trading_positions
            ALTER COLUMN {col} TYPE NUMERIC(38, 18) USING {col}::numeric
        """)

    # ── TradeHistory: gas wei, USD value, decimals sidecars ────────

    op.execute("""
        ALTER TABLE public.trade_history
        ADD COLUMN IF NOT EXISTS from_token_decimals INTEGER
    """)
    op.execute("""
        ALTER TABLE public.trade_history
        ADD COLUMN IF NOT EXISTS to_token_decimals INTEGER
    """)
    op.execute("""
        ALTER TABLE public.trade_history
        ADD COLUMN IF NOT EXISTS gas_price_wei NUMERIC(78, 0)
    """)
    op.execute("""
        UPDATE public.trade_history
        SET gas_price_wei = (gas_price_gwei * 1e9)::numeric(78, 0)
        WHERE gas_price_wei IS NULL AND gas_price_gwei IS NOT NULL
    """)
    op.execute("ALTER TABLE public.trade_history DROP COLUMN IF EXISTS gas_price_gwei")

    op.execute("""
        ALTER TABLE public.trade_history
        ALTER COLUMN value_usd TYPE NUMERIC(38, 18) USING value_usd::numeric
    """)


def downgrade() -> None:
    # Reverse is lossy by design (NUMERIC → REAL truncates) but the
    # shape matches the pre-fix model so the ORM is happy on rollback.

    # ── TradeHistory ──
    op.execute("""
        ALTER TABLE public.trade_history
        ALTER COLUMN value_usd TYPE DOUBLE PRECISION USING value_usd::double precision
    """)
    op.execute("""
        ALTER TABLE public.trade_history
        ADD COLUMN IF NOT EXISTS gas_price_gwei DOUBLE PRECISION
    """)
    op.execute("""
        UPDATE public.trade_history
        SET gas_price_gwei = (gas_price_wei / 1e9)::double precision
        WHERE gas_price_gwei IS NULL AND gas_price_wei IS NOT NULL
    """)
    op.execute("ALTER TABLE public.trade_history DROP COLUMN IF EXISTS gas_price_wei")
    op.execute("ALTER TABLE public.trade_history DROP COLUMN IF EXISTS from_token_decimals")
    op.execute("ALTER TABLE public.trade_history DROP COLUMN IF EXISTS to_token_decimals")

    # ── TradingPosition ──
    for col in (
        "entry_price_usd",
        "exit_price_usd",
        "stop_loss_usd",
        "take_profit_usd",
    ):
        op.execute(f"""
            ALTER TABLE public.trading_positions
            ALTER COLUMN {col} TYPE DOUBLE PRECISION USING {col}::double precision
        """)
    op.execute("""
        ALTER TABLE public.trading_positions
        ADD COLUMN IF NOT EXISTS amount DOUBLE PRECISION
    """)
    op.execute("""
        UPDATE public.trading_positions
        SET amount = (amount_raw / power(10::numeric, token_decimals))::double precision
        WHERE amount IS NULL AND amount_raw IS NOT NULL
    """)
    op.execute("""
        UPDATE public.trading_positions
        SET amount = 0
        WHERE amount IS NULL
    """)
    op.execute("ALTER TABLE public.trading_positions ALTER COLUMN amount SET NOT NULL")
    op.execute("ALTER TABLE public.trading_positions DROP COLUMN IF EXISTS amount_raw")
    op.execute("ALTER TABLE public.trading_positions DROP COLUMN IF EXISTS token_decimals")
