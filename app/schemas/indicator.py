from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IndicatorInputCreate(BaseModel):
    """Incoming webhook payload from TradingView or NinjaTrader."""

    symbol: str = Field(
        ..., min_length=1, max_length=20, examples=["EURUSD", "NQ", "AAPL"]
    )
    indicator_name: str = Field(
        ..., min_length=1, max_length=100, examples=["RSI", "MACD", "VWAP"]
    )
    signal_value: float = Field(..., examples=[67.5, -0.0023])
    bias: str = Field(
        ..., pattern=r"^(LONG|SHORT|NEUTRAL)$",
        description="Directional bias: LONG, SHORT, or NEUTRAL",
    )
    extra_data: dict[str, Any] | None = Field(
        default=None,
        description="Optional free-form metadata from the source platform",
    )


class IndicatorInputResponse(BaseModel):
    """Confirmation returned after storing an indicator signal."""

    id: int
    symbol: str
    indicator_name: str
    signal_value: float
    bias: str
    extra_data: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
