from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.signal import Signal
from app.services.market_data import fetch_market_summary
from app.agents.claude_agent import generate_signal

router = APIRouter()


@router.post("/generate/{symbol}")
def generate(symbol: str, db: Session = Depends(get_db)):
    try:
        market_data = fetch_market_summary(symbol.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    result = generate_signal(market_data)

    signal = Signal(
        symbol=symbol.upper(),
        direction=result["direction"],
        confidence=result["confidence"],
        reasoning=result["reasoning"],
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    return {
        "id": signal.id,
        "symbol": signal.symbol,
        "direction": signal.direction,
        "confidence": signal.confidence,
        "reasoning": signal.reasoning,
        "market_data": market_data,
    }


@router.get("/history/{symbol}")
def history(symbol: str, db: Session = Depends(get_db)):
    signals = (
        db.query(Signal)
        .filter(Signal.symbol == symbol.upper())
        .order_by(Signal.created_at.desc())
        .limit(20)
        .all()
    )
    return signals
