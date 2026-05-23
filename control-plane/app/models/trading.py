"""Bob Manager — Trading position + trade history ORM models."""

import uuid
from datetime import datetime

from sqlalchemy import String, Float, DateTime, Text, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TradingPosition(Base):
    """A tracked trading position (open or closed)."""

    __tablename__ = "trading_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="???")
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    entry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exit_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open, closed, stopped
    stop_loss_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lab_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )


class TradeHistory(Base):
    """Record of an executed trade or transaction."""

    __tablename__ = "trade_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    tx_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # swap, send, receive, approve
    from_token: Mapped[str | None] = mapped_column(String(42), nullable=True)
    from_token_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    from_amount: Mapped[str | None] = mapped_column(String(78), nullable=True)
    to_token: Mapped[str | None] = mapped_column(String(42), nullable=True)
    to_token_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_amount: Mapped[str | None] = mapped_column(String(78), nullable=True)
    gas_used: Mapped[int | None] = mapped_column(nullable=True)
    gas_price_gwei: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    lab_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
