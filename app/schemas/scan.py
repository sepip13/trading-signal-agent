from typing import Any
from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    symbols: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of symbols to scan, e.g. ['NQ', 'ES', 'GC'].",
        examples=[["NQ", "ES", "GC", "DXY"]],
    )
    agent_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum absolute bias score (0–1) required to trigger the full Claude agent. "
            "Symbols below this threshold get bias-only results. Default 0.4."
        ),
    )


class BiasSummary(BaseModel):
    direction: str
    confidence: int
    score: float
    factors: list[dict[str, Any]]


class ScanResult(BaseModel):
    symbol: str
    bias: BiasSummary | None = None
    agent_triggered: bool = False
    signal: dict[str, Any] | None = None
    error: str | None = None


class ScanResponse(BaseModel):
    scanned: int
    agents_triggered: int
    results: list[ScanResult]
