"""Bob Manager — Trading repository: positions + trade history CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import TradingPosition, TradeHistory


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
        amount: float,
        entry_price_usd: float | None = None,
        entry_tx_hash: str | None = None,
        stop_loss_usd: float | None = None,
        take_profit_usd: float | None = None,
        notes: str = "",
        lab_id: uuid.UUID | None = None,
    ) -> dict:
        pos = TradingPosition(
            id=uuid.uuid4(),
            wallet_address=wallet_address.lower(),
            chain=chain,
            token_address=token_address.lower(),
            token_symbol=token_symbol,
            amount=amount,
            entry_price_usd=entry_price_usd,
            entry_tx_hash=entry_tx_hash,
            stop_loss_usd=stop_loss_usd,
            take_profit_usd=take_profit_usd,
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
        exit_price_usd: float | None = None,
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
        pos.exit_price_usd = exit_price_usd
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

    async def get_portfolio_pnl(self) -> dict | None:
        stmt = select(TradingPosition).where(TradingPosition.status == "open")
        result = await self.db.execute(stmt)
        positions = result.scalars().all()
        if not positions:
            return None

        total_entry = sum(
            (p.entry_price_usd or 0) * (p.amount or 0) for p in positions
        )
        return {
            "position_count": len(positions),
            "total_entry_value": round(total_entry, 2),
            "positions": [self._pos_to_dict(p) for p in positions],
        }

    def _pos_to_dict(self, p: TradingPosition) -> dict:
        return {
            "id": str(p.id),
            "wallet_address": p.wallet_address,
            "chain": p.chain,
            "token_address": p.token_address,
            "token_symbol": p.token_symbol,
            "amount": p.amount,
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
        from_amount: str = "",
        to_token: str = "",
        to_amount: str = "",
        value_usd: float | None = None,
        position_id: uuid.UUID | None = None,
        lab_id: uuid.UUID | None = None,
    ) -> dict:
        trade = TradeHistory(
            id=uuid.uuid4(),
            wallet_address=wallet_address.lower(),
            chain=chain,
            tx_hash=tx_hash,
            tx_type=tx_type,
            from_token=from_token,
            from_amount=from_amount,
            to_token=to_token,
            to_amount=to_amount,
            value_usd=value_usd,
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
        return {
            "id": str(t.id),
            "wallet_address": t.wallet_address,
            "chain": t.chain,
            "tx_hash": t.tx_hash,
            "tx_type": t.tx_type,
            "from_token": t.from_token,
            "from_token_symbol": t.from_token_symbol,
            "from_amount": t.from_amount,
            "to_token": t.to_token,
            "to_token_symbol": t.to_token_symbol,
            "to_amount": t.to_amount,
            "gas_used": t.gas_used,
            "gas_price_gwei": t.gas_price_gwei,
            "value_usd": t.value_usd,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "position_id": str(t.position_id) if t.position_id else None,
            "lab_id": str(t.lab_id) if t.lab_id else None,
        }
