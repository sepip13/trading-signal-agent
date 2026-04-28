import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.claude_agent import run_agent
from app.db.session import get_db
from app.schemas.signal import AnalyzeResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{symbol}",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a symbol",
    description=(
        "Triggers the Claude agent to analyze a symbol using ICT/Smart Money logic. "
        "The agent autonomously fetches indicator signals and market data, "
        "then stores and returns the resulting trading signal."
    ),
)
def analyze(symbol: str, db: Session = Depends(get_db)):
    sym = symbol.upper().strip()
    logger.info("Analysis requested for %s", sym)

    try:
        result = run_agent(f"Analyze {sym}", db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        logger.exception("Agent failed for %s", sym)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )

    return result
