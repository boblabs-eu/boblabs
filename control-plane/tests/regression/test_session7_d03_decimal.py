"""D03 — trading precision regression suite.

Pre-fix: ``trading_positions.amount`` + the four ``*_price_usd`` columns
and ``trade_history.gas_price_gwei`` / ``value_usd`` were ``Float``
columns. ``Decimal('0.1') + Decimal('0.2')`` rounded to
``0.30000000000000004`` once it round-tripped through the DB.

Post-fix:
* ``amount_raw`` is ``NUMERIC(78, 0)`` (on-chain wei integer); a sibling
  ``token_decimals INTEGER NOT NULL`` carries the scale.
* USD prices are ``NUMERIC(38, 18)``.
* Gas is ``gas_price_wei NUMERIC(78, 0)``.

These assertions run against the live ephemeral Postgres test DB via
the shared conftest. They lock both the storage shape (Decimal-clean
round trip) and the helper invariants (``to_raw`` / ``from_raw``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models.trading import TradeHistory, TradingPosition
from app.repositories.trading_repo import TradingRepo
from app.services.trading_units import decimals_for, from_raw, to_raw
from sqlalchemy import select

pytestmark = pytest.mark.regression


# ── Unit-level helper tests (no DB) ──────────────────────────────────


def test_d03_to_raw_round_trips_18_decimals():
    raw = to_raw(Decimal("1.5"), 18)
    assert raw == 1_500_000_000_000_000_000
    assert from_raw(raw, 18) == Decimal("1.5")


def test_d03_to_raw_round_trips_btc():
    # 1 BTC = 10^8 satoshi (not 10^12 — quick op called this out)
    raw = to_raw(Decimal("1"), 8)
    assert raw == 100_000_000
    assert from_raw(raw, 8) == Decimal("1")


def test_d03_decimals_for_known_and_unknown():
    assert decimals_for("ETH") == 18
    assert decimals_for("eth") == 18  # case-insensitive
    assert decimals_for("BTC") == 8
    assert decimals_for("USDC") == 6
    assert decimals_for("RANDOMCOIN") == 18  # safe ERC-20 default
    assert decimals_for(None) == 18


def test_d03_to_raw_rejects_negative_decimals():
    with pytest.raises(ValueError):
        to_raw(Decimal("1"), -1)
    with pytest.raises(ValueError):
        from_raw(0, -5)


# ── DB-level round-trip tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_d03_position_wei_round_trip(db):
    """Insert a position with a wei-precise amount; read back via the
    repo; assert ``from_raw(amount_raw, token_decimals)`` returns the
    exact human Decimal (not a rounded float)."""
    repo = TradingRepo(db)
    pos = await repo.open_position(
        wallet_address="0xabc0000000000000000000000000000000000000",
        chain="ethereum",
        token_address="0xdef0000000000000000000000000000000000000",
        token_symbol="ETH",
        amount=Decimal("1.5"),
        entry_price_usd=Decimal("3000.5"),
    )
    await db.commit()

    # token_decimals defaulted to 18 (ETH), amount_raw = 1.5 * 10^18.
    assert pos["token_decimals"] == 18
    assert pos["amount_raw"] == "1500000000000000000"
    assert pos["amount"] == Decimal("1.5")
    assert pos["entry_price_usd"] == Decimal("3000.5")

    # Pull the raw row to confirm the storage matches.
    row = (
        await db.execute(select(TradingPosition).where(TradingPosition.id == uuid.UUID(pos["id"])))
    ).scalar_one()
    assert row.amount_raw == Decimal("1500000000000000000")
    assert row.token_decimals == 18
    assert row.entry_price_usd == Decimal("3000.5")


@pytest.mark.asyncio
async def test_d03_position_btc_uses_8_decimals(db):
    """A position opened with token_symbol='BTC' must default to 8
    decimals and store 1 BTC as 10^8 satoshi."""
    repo = TradingRepo(db)
    pos = await repo.open_position(
        wallet_address="0xabc0000000000000000000000000000000000000",
        chain="ethereum",
        token_address="0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
        token_symbol="BTC",
        amount=Decimal("1"),
    )
    await db.commit()

    assert pos["token_decimals"] == 8
    assert pos["amount_raw"] == "100000000"
    assert pos["amount"] == Decimal("1")


@pytest.mark.asyncio
async def test_d03_usd_price_lossless(db):
    """USD prices use NUMERIC(38, 18); a tricky value must survive a
    round trip byte-equal (no Float-style truncation)."""
    repo = TradingRepo(db)
    tricky = Decimal("1234.567890123456789012")
    pos = await repo.open_position(
        wallet_address="0xabc0000000000000000000000000000000000000",
        chain="ethereum",
        token_address="0xdef0000000000000000000000000000000000000",
        token_symbol="ETH",
        amount=Decimal("0.001"),
        entry_price_usd=tricky,
    )
    await db.commit()

    row = (
        await db.execute(select(TradingPosition).where(TradingPosition.id == uuid.UUID(pos["id"])))
    ).scalar_one()
    assert row.entry_price_usd == tricky


@pytest.mark.asyncio
async def test_d03_zero_point_one_plus_two_stays_exact(db):
    """The classic Float trap: 0.1 + 0.2 stored as a Float and read back
    returns 0.30000000000000004. With NUMERIC(38, 18) it must round-trip
    byte-exact to Decimal('0.3')."""
    repo = TradingRepo(db)
    trade = await repo.record_trade(
        wallet_address="0xabc0000000000000000000000000000000000000",
        chain="ethereum",
        tx_hash="0x" + ("a" * 64),
        tx_type="swap",
        value_usd=Decimal("0.1") + Decimal("0.2"),
    )
    await db.commit()

    row = (
        await db.execute(select(TradeHistory).where(TradeHistory.id == uuid.UUID(trade["id"])))
    ).scalar_one()
    assert row.value_usd == Decimal("0.3")
    # Specifically reject the float-truncation result.
    assert row.value_usd != Decimal("0.30000000000000004")


@pytest.mark.asyncio
async def test_d03_gas_price_wei_round_trip(db):
    """Gas was stored as gwei Float; now stored as wei NUMERIC(78, 0).
    Verify the new column carries the on-chain integer losslessly."""
    repo = TradingRepo(db)
    # 30 gwei = 30 * 10^9 wei
    trade = await repo.record_trade(
        wallet_address="0xabc0000000000000000000000000000000000000",
        chain="ethereum",
        tx_hash="0x" + ("b" * 64),
        tx_type="swap",
        gas_price_wei=Decimal("30000000000"),
    )
    await db.commit()

    row = (
        await db.execute(select(TradeHistory).where(TradeHistory.id == uuid.UUID(trade["id"])))
    ).scalar_one()
    assert row.gas_price_wei == Decimal("30000000000")
    # _trade_to_dict surfaces a derived gas_price_gwei for legacy LLM display.
    assert trade["gas_price_gwei"] == Decimal("30")


# ── Source-introspection guard ───────────────────────────────────────


def test_d03_float_removed_from_trading_models():
    """The migration shipped only matters if the ORM no longer reaches
    for Float anywhere in trading.py."""
    import re
    from pathlib import Path

    # In the test container control-plane/ is mounted to /app, so the
    # source we want is at /app/app/models/trading.py (parents[2] + app/...).
    src = Path(__file__).resolve().parents[2] / "app" / "models" / "trading.py"
    body = src.read_text(encoding="utf-8")
    # Strip triple-quoted docstrings and # comments before scanning, so
    # historical mentions like "(Float) was retired" in the module
    # docstring don't trip the assertion.
    code_only = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)
    code_only = re.sub(r"'''.*?'''", "", code_only, flags=re.DOTALL)
    code_only = re.sub(r"#.*$", "", code_only, flags=re.MULTILINE)
    assert "Float" not in code_only, (
        "D03: models/trading.py must not import or reference Float as a SQLA type"
    )
    # Positive assertion: the new shape is present.
    assert "amount_raw" in body
    assert "token_decimals" in body
    assert "gas_price_wei" in body
