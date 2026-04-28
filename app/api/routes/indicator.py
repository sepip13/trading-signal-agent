import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.indicator_input import IndicatorInput
from app.schemas.indicator import IndicatorInputCreate, IndicatorInputResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=IndicatorInputResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Receive an indicator signal",
    description="Ingests indicator signals from TradingView webhooks or NinjaTrader.",
)
def create_indicator_input(
    payload: IndicatorInputCreate,
    db: Session = Depends(get_db),
):
    record = IndicatorInput(
        symbol=payload.symbol.upper(),
        indicator_name=payload.indicator_name,
        signal_value=payload.signal_value,
        bias=payload.bias,
        extra_data=payload.extra_data,
    )

    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to store indicator input")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store indicator input.",
        ) from exc

    return record
