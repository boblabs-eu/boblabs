"""Bob Manager — Theme Color ORM model."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ThemeColor(Base):
    """Maps a theme name to a hex color."""

    __tablename__ = "theme_colors"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    color: Mapped[str] = mapped_column(String(7), default="#a855f7")
