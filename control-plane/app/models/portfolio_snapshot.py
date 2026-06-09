"""Bob Manager — Portfolio snapshot model (time-series)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortfolioSnapshot(Base):
    """One point-in-time value snapshot for a single wallet."""

    __tablename__ = "portfolio_snapshots"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    wallet_label: Mapped[str] = mapped_column(String(255), default="")
    total_value_usd: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
