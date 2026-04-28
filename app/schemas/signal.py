from datetime import datetime

from pydantic import BaseModel, Field


class SignalResponse(BaseModel):
    """Signal record returned from DB."""

    id: int
    symbol: str
    direction: str = Field(description="LONG | SHORT | NEUTRAL")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reasoning: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalyzeResponse(BaseModel):
    """Returned after a successful /analyze/{symbol} call."""

    signal_id: int
    symbol: str
    direction: str = Field(description="LONG | SHORT | NEUTRAL")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reasoning: str
    created_at: datetime
    stored: bool = True
