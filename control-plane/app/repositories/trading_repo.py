"""Bob Manager — Trading repository: positions + trade history CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import TradeHistory, TradingPosition
from app.services.trading_units import (
    decimals_for,
    from_raw,
    to_raw,
)


def _to_decimal(value) -> Decimal | None:
    """Cast a number-like input to Decimal without leaking float quantum.

    ``Decimal(0.1)`` carries every bit of the binary-float
    representation, producing a 50-digit tail. ``Decimal(str(0.1))``
    instead gives ``Decimal('0.1')`` (what the caller meant).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


class TradingRepo:
    """Data access for trading positions and trade history."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Positions ────────────────────────────────────────────────────────

    async def open_position(
        self,
        wallet_address: str,
        chain: str,
        token_address: str,
        token_symbol: str,
        amount: Decimal | int | str,
        token_decimals: int | None = None,
        entry_price_usd: Decimal | str | None = None,
        entry_tx_hash: str | None = None,
        stop_loss_usd: Decimal | str | None = None,
        take_profit_usd: Decimal | str | None = None,
        notes: str = "",
        lab_id: uuid.UUID | None = None,
    ) -> dict:
        # D03 — caller supplies the human-readable Decimal; we store the
        # on-chain wei integer + the token_decimals sibling.
        if token_decimals is None:
            token_decimals = decimals_for(token_symbol)
        amount_raw = to_raw(amount, token_decimals)
        pos = TradingPosition(
            id=uuid.uuid4(),
            wallet_address=wallet_address.lower(),
            chain=chain,
            token_address=token_address.lower(),
            token_symbol=token_symbol,
            amount_raw=Decimal(amount_raw),
            token_decimals=token_decimals,
            entry_price_usd=_to_decimal(entry_price_usd),
            entry_tx_hash=entry_tx_hash,
            stop_loss_usd=_to_decimal(stop_loss_usd),
            take_profit_usd=_to_decimal(take_profit_usd),
            notes=notes,
            lab_id=lab_id,
            status="open",
        )
        self.db.add(pos)
        await self.db.flush()
        return self._pos_to_dict(pos)

    async def close_position(
        self,
        position_id: str,
        exit_price_usd: Decimal | str | None = None,
        exit_tx_hash: str = "",
    ) -> dict | None:
        uid = uuid.UUID(position_id)
        result = await self.db.execute(
            select(TradingPosition).where(
                TradingPosition.id == uid,
                TradingPosition.status == "open",
            )
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return None

        pos.status = "closed"
        pos.exit_price_usd = _to_decimal(exit_price_usd)
        pos.exit_tx_hash = exit_tx_hash
        pos.exit_at = datetime.now(timezone.utc)
        await self.db.flush()
        return self._pos_to_dict(pos)

    async def list_positions(
        self,
        wallet_address: str | None = None,
        status: str = "open",
        limit: int = 20,
    ) -> list[dict]:
        stmt = select(TradingPosition).order_by(TradingPosition.entry_at.desc())
        if wallet_address:
            stmt = stmt.where(TradingPosition.wallet_address == wallet_address.lower())
        if status != "all":
            stmt = stmt.where(TradingPosition.status == status)
        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        return [self._pos_to_dict(p) for p in result.scalars().all()]

    async def get_portfolio_pnl(self, lab_id: uuid.UUID | None = None) -> dict | None:
        """P06 — when called from a lab tool, ``lab_id`` filters to that
        lab's positions only. Calling without ``lab_id`` returns the
        whole hot-wallet portfolio and is reserved for admin/operator
        flows (no UI today). The audit flagged this method as a
        cross-tenant scan path because every lab that has the trading
        tool used to see every other lab's positions.
        """
        stmt = select(TradingPosition).where(TradingPosition.status == "open")
        if lab_id is not None:
            stmt = stmt.where(TradingPosition.lab_id == lab_id)
        result = await self.db.execute(stmt)
        positions = result.scalars().all()
        if not positions:
            return None

        # D03 — total_entry = sum(entry_price * human_amount) all in Decimal.
        # ``amount_raw / 10^token_decimals`` produces a lossless Decimal
        # we can multiply against ``entry_price_usd`` (also Numeric).
        total_entry = sum(
            (
                (p.entry_price_usd or Decimal(0)) * from_raw(p.amount_raw or 0, p.token_decimals)
                for p in positions
            ),
            start=Decimal(0),
        )
        return {
            "position_count": len(positions),
            # Round at the API boundary, never on disk.
            "total_entry_value": float(round(total_entry, 2)),
            "positions": [self._pos_to_dict(p) for p in positions],
        }

    def _pos_to_dict(self, p: TradingPosition) -> dict:
        # D03 — render the human Decimal here; the raw wei stays
        # available for consumers that want byte-exact reconciliation
        # against on-chain logs.
        human_amount = (
            from_raw(p.amount_raw, p.token_decimals) if p.amount_raw is not None else None
        )
        return {
            "id": str(p.id),
            "wallet_address": p.wallet_address,
            "chain": p.chain,
            "token_address": p.token_address,
            "token_symbol": p.token_symbol,
            "amount": human_amount,
            "amount_raw": str(p.amount_raw) if p.amount_raw is not None else None,
            "token_decimals": p.token_decimals,
            "entry_price_usd": p.entry_price_usd,
            "entry_tx_hash": p.entry_tx_hash,
            "entry_at": p.entry_at.isoformat() if p.entry_at else None,
            "exit_price_usd": p.exit_price_usd,
            "exit_tx_hash": p.exit_tx_hash,
            "exit_at": p.exit_at.isoformat() if p.exit_at else None,
            "status": p.status,
            "stop_loss_usd": p.stop_loss_usd,
            "take_profit_usd": p.take_profit_usd,
            "notes": p.notes,
            "lab_id": str(p.lab_id) if p.lab_id else None,
        }

    # ── Trade History ────────────────────────────────────────────────────

    async def record_trade(
        self,
        wallet_address: str,
        chain: str,
        tx_hash: str,
        tx_type: str,
        from_token: str = "",
        from_token_symbol: str | None = None,
        from_amount: str = "",
        from_token_decimals: int | None = None,
        to_token: str = "",
        to_token_symbol: str | None = None,
        to_amount: str = "",
        to_token_decimals: int | None = None,
        gas_price_wei: Decimal | int | str | None = None,
        value_usd: Decimal | str | None = None,
        position_id: uuid.UUID | None = None,
        lab_id: uuid.UUID | None = None,
    ) -> dict:
        # D03 — derive decimals from symbol if the caller didn't supply
        # one. ``from_amount``/``to_amount`` are wei-as-decimal-string,
        # matching the pre-existing String(78) shape.
        if from_token_decimals is None and from_token_symbol:
            from_token_decimals = decimals_for(from_token_symbol)
        if to_token_decimals is None and to_token_symbol:
            to_token_decimals = decimals_for(to_token_symbol)
        trade = TradeHistory(
            id=uuid.uuid4(),
            wallet_address=wallet_address.lower(),
            chain=chain,
            tx_hash=tx_hash,
            tx_type=tx_type,
            from_token=from_token,
            from_token_symbol=from_token_symbol,
            from_amount=from_amount,
            from_token_decimals=from_token_decimals,
            to_token=to_token,
            to_token_symbol=to_token_symbol,
            to_amount=to_amount,
            to_token_decimals=to_token_decimals,
            gas_price_wei=_to_decimal(gas_price_wei),
            value_usd=_to_decimal(value_usd),
            position_id=position_id,
            lab_id=lab_id,
        )
        self.db.add(trade)
        await self.db.flush()
        return self._trade_to_dict(trade)

    async def get_trade_history(
        self,
        wallet_address: str | None = None,
        chain: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        stmt = select(TradeHistory).order_by(TradeHistory.timestamp.desc())
        if wallet_address:
            stmt = stmt.where(TradeHistory.wallet_address == wallet_address.lower())
        if chain:
            stmt = stmt.where(TradeHistory.chain == chain)
        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        return [self._trade_to_dict(t) for t in result.scalars().all()]

    def _trade_to_dict(self, t: TradeHistory) -> dict:
        # D03 — render both raw wei (gas_price_wei) and the legacy
        # gwei representation so existing LLM-facing formatters keep
        # working without changes.
        gas_gwei: Decimal | None = None
        if t.gas_price_wei is not None:
            gas_gwei = Decimal(t.gas_price_wei) / Decimal(10**9)
        return {
            "id": str(t.id),
            "wallet_address": t.wallet_address,
            "chain": t.chain,
            "tx_hash": t.tx_hash,
            "tx_type": t.tx_type,
            "from_token": t.from_token,
            "from_token_symbol": t.from_token_symbol,
            "from_amount": t.from_amount,
            "from_token_decimals": t.from_token_decimals,
            "to_token": t.to_token,
            "to_token_symbol": t.to_token_symbol,
            "to_amount": t.to_amount,
            "to_token_decimals": t.to_token_decimals,
            "gas_used": t.gas_used,
            "gas_price_wei": str(t.gas_price_wei) if t.gas_price_wei is not None else None,
            "gas_price_gwei": gas_gwei,
            "value_usd": t.value_usd,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "position_id": str(t.position_id) if t.position_id else None,
            "lab_id": str(t.lab_id) if t.lab_id else None,
        }
