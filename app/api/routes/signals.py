import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signal import Signal
from app.schemas.signal import SignalResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ── GET /signals/latest ────────────────────────────────────────────
# IMPORTANT: must be registered before /{symbol} to avoid route conflict.

@router.get(
    "/latest",
    response_model=list[SignalResponse],
    summary="Latest signal per symbol",
    description="Returns the single most recent signal for every symbol in the DB.",
)
def latest(db: Session = Depends(get_db)):
    # Subquery: max created_at per symbol
    subq = (
        db.query(
            Signal.symbol,
            func.max(Signal.created_at).label("max_at"),
        )
        .group_by(Signal.symbol)
        .subquery()
    )

    signals = (
        db.query(Signal)
        .join(
            subq,
            (Signal.symbol == subq.c.symbol)
            & (Signal.created_at == subq.c.max_at),
        )
        .order_by(Signal.symbol)
        .all()
    )
    return signals


# ── GET /signals/{symbol} ──────────────────────────────────────────

@router.get(
    "/{symbol}",
    response_model=list[SignalResponse],
    summary="Signal history for a symbol",
    description="Returns the N most recent signals for a given symbol (default 10, max 100).",
)
def history(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=100, description="Number of records to return"),
    db: Session = Depends(get_db),
):
    sym = symbol.upper().strip()
    signals = (
        db.query(Signal)
        .filter(Signal.symbol == sym)
        .order_by(Signal.created_at.desc())
        .limit(limit)
        .all()
    )
    if not signals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No signals found for symbol '{sym}'.",
        )
    return signals
