from datetime import datetime

from sqlalchemy import String, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IndicatorInput(Base):
    __tablename__ = "indicator_inputs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    indicator_name: Mapped[str] = mapped_column(String(100), index=True)
    signal_value: Mapped[float] = mapped_column(Float)
    bias: Mapped[str] = mapped_column(String(20))  # LONG / SHORT / NEUTRAL
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
