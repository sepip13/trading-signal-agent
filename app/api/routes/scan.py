"""
Scan endpoint — POST /api/v1/scan

Runs compute_bias on all requested symbols in parallel (ThreadPoolExecutor).
Symbols whose |score| >= agent_threshold trigger the full Claude agent loop,
also in parallel.

Flow
----
1. Validate + normalise symbols
2. Phase 1 (parallel): run score_bias for every symbol
   - Each worker gets its own DB session
3. Phase 2 (parallel): run Claude agent for symbols that cleared the threshold
   - Reuses the same per-symbol DB session
4. Assemble ScanResponse and return
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.agents.claude_agent import run_agent
from app.db.session import SessionLocal
from app.models.indicator_input import IndicatorInput
from app.schemas.scan import BiasSummary, ScanRequest, ScanResponse, ScanResult
from app.services.bias_engine import score_bias
from app.services.market_data import get_market_snapshot

logger = logging.getLogger(__name__)

router = APIRouter()

# Cap on simultaneous yfinance / Anthropic calls
_MAX_BIAS_WORKERS = 6
_MAX_AGENT_WORKERS = 3


# ── Worker functions (run in threads) ─────────────────────────────

def _bias_worker(symbol: str) -> tuple[str, BiasSummary | None, float, str | None]:
    """
    Phase 1 worker: fetch snapshot + read DB indicators → compute bias score.
    Returns (symbol, BiasSummary | None, abs_score, error | None).
    Each worker opens and closes its own DB session.
    """
    db = SessionLocal()
    try:
        snapshot = get_market_snapshot(symbol)

        rows = (
            db.query(IndicatorInput)
            .filter(IndicatorInput.symbol == symbol)
            .order_by(IndicatorInput.created_at.desc())
            .limit(10)
            .all()
        )
        indicator_signals = [
            {
                "indicator_name": r.indicator_name,
                "signal_value": r.signal_value,
                "bias": r.bias,
                "extra_data": r.extra_data,
            }
            for r in rows
        ]

        result = score_bias(snapshot, indicator_signals)
        summary = BiasSummary(**result.summary())
        return symbol, summary, abs(result.score), None

    except Exception as exc:
        logger.warning("[scan] bias_worker symbol=%s error=%s", symbol, exc)
        return symbol, None, 0.0, str(exc)
    finally:
        db.close()


def _agent_worker(symbol: str) -> tuple[str, dict | None, str | None]:
    """
    Phase 2 worker: run the full Claude agent for one symbol.
    Returns (symbol, signal_dict | None, error | None).
    """
    db = SessionLocal()
    try:
        signal = run_agent(f"Analyze {symbol}", db)
        return symbol, signal, None
    except Exception as exc:
        logger.error("[scan] agent_worker symbol=%s error=%s", symbol, exc)
        return symbol, None, str(exc)
    finally:
        db.close()


# ── Route ──────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Multi-symbol bias scan",
    description=(
        "Scores directional bias for all requested symbols in parallel. "
        "Symbols where |score| >= agent_threshold trigger the full Claude agent "
        "to produce and persist a trading signal. Others return bias-only results."
    ),
)
def scan(payload: ScanRequest):
    symbols = [s.upper().strip() for s in payload.symbols]
    symbols = list(dict.fromkeys(symbols))  # deduplicate, preserve order
    threshold = payload.agent_threshold

    logger.info("[scan] symbols=%s threshold=%.2f", symbols, threshold)

    # ── Phase 1: bias scoring (parallel) ──────────────────────────
    bias_by_symbol: dict[str, BiasSummary | None] = {}
    score_by_symbol: dict[str, float] = {}
    errors_by_symbol: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=min(_MAX_BIAS_WORKERS, len(symbols))) as pool:
        futures = {pool.submit(_bias_worker, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, summary, abs_score, error = future.result()
            bias_by_symbol[sym] = summary
            score_by_symbol[sym] = abs_score
            if error:
                errors_by_symbol[sym] = error

    # Determine which symbols clear the threshold
    to_agent = [
        sym for sym in symbols
        if score_by_symbol.get(sym, 0.0) >= threshold
        and sym not in errors_by_symbol
    ]

    logger.info(
        "[scan] bias complete — %d/%d symbols cleared threshold (%.2f): %s",
        len(to_agent), len(symbols), threshold, to_agent,
    )

    # ── Phase 2: Claude agent (parallel, only cleared symbols) ────
    agent_signals: dict[str, dict | None] = {}
    agent_errors: dict[str, str] = {}

    if to_agent:
        with ThreadPoolExecutor(max_workers=min(_MAX_AGENT_WORKERS, len(to_agent))) as pool:
            futures = {pool.submit(_agent_worker, sym): sym for sym in to_agent}
            for future in as_completed(futures):
                sym, signal, error = future.result()
                if error:
                    agent_errors[sym] = error
                else:
                    agent_signals[sym] = signal

    # ── Assemble response ─────────────────────────────────────────
    results: list[ScanResult] = []
    for sym in symbols:
        agent_triggered = sym in to_agent
        error = errors_by_symbol.get(sym) or agent_errors.get(sym)

        results.append(ScanResult(
            symbol=sym,
            bias=bias_by_symbol.get(sym),
            agent_triggered=agent_triggered,
            signal=agent_signals.get(sym),
            error=error,
        ))

    agents_triggered = len([r for r in results if r.agent_triggered])

    return ScanResponse(
        scanned=len(results),
        agents_triggered=agents_triggered,
        results=results,
    )
