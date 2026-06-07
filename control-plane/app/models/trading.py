"""Bob Manager — Trading position + trade history ORM models."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TradingPosition(Base):
    """A tracked trading position (open or closed).

    D03 — on-chain amounts are stored as integer wei (the token's
    smallest indivisible unit, e.g. 1 ETH = 10^18 wei, 1 BTC = 10^8
    satoshi). The ``token_decimals`` sibling column carries the scale
    so display code can render the human Decimal via
    :func:`app.services.trading_units.from_raw`. USD prices live in
    ``Numeric(38, 18)`` — bounded, lossless, no wei semantics needed.
    """

    __tablename__ = "trading_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="???")
    # D03 — on-chain integer (wei / satoshi / 10^decimals units).
    amount_raw: Mapped[Decimal] = mapped_column(
        Numeric(78, 0), nullable=False, default=0
    )
    # D03 — decimals metadata so from_raw() can render the human value.
    # Default 18 matches the ERC-20 spec; per-token overrides happen at
    # write time via trading_units.decimals_for(symbol).
    token_decimals: Mapped[int] = mapped_column(
        Integer, nullable=False, default=18, server_default="18"
    )
    entry_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    entry_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    entry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exit_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    exit_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open, closed, stopped
    stop_loss_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    take_profit_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lab_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )


class TradeHistory(Base):
    """Record of an executed trade or transaction.

    D03 — ``gas_price_gwei`` (Float) was retired in favour of
    ``gas_price_wei`` (Numeric(78, 0)). The from/to amounts already
    used the String(78) wei-as-string pattern; ``from_token_decimals`` /
    ``to_token_decimals`` are added so display code can render the
    correct human value per token.
    """

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
    from_token_decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_token: Mapped[str | None] = mapped_column(String(42), nullable=True)
    to_token_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_amount: Mapped[str | None] = mapped_column(String(78), nullable=True)
    to_token_decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_used: Mapped[int | None] = mapped_column(nullable=True)
    gas_price_wei: Mapped[Decimal | None] = mapped_column(
        Numeric(78, 0), nullable=True
    )
    value_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    lab_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
