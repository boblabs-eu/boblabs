"""Bob Manager — Web3 settings singleton model."""

from datetime import datetime

from sqlalchemy import Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Web3Settings(Base):
    """Singleton row storing user-configurable Web3 parameters."""

    __tablename__ = "web3_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_interval: Mapped[int] = mapped_column(Integer, default=300)
    retention_full_hours: Mapped[int] = mapped_column(Integer, default=168)
    retention_step_hours: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
