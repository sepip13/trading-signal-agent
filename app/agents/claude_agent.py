"""
Claude Agent Core — Step 6
Tool-use agentic loop with ICT / Smart Money analysis logic.

Tools exposed to Claude:
  get_market_data(symbol)          → live price snapshot via yfinance
  get_indicator_signals(symbol)    → latest indicator rows from DB
  compute_bias(symbol)             → runs BiasEngine, returns scored direction
  store_signal(...)                → persists final signal to DB

Entrypoint:
  run_agent(query, db) → dict (the stored signal)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.indicator_input import IndicatorInput
from app.models.signal import Signal
from app.services.market_data import get_market_snapshot
from app.services.bias_engine import score_bias

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


# ── System prompt ──────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a professional futures trading analyst using ICT (Inner Circle Trader) \
and Smart Money Concepts (SMC).

When analyzing a symbol, follow this exact sequence:

STEP 1 — Call compute_bias(symbol).
  This runs the BiasEngine: reads indicator signals from DB + live market data,
  and returns a scored direction with per-factor breakdown.
  Read the result carefully:
  - bias_result.direction  → the engine's computed direction
  - bias_result.score      → raw weighted score (-1..+1)
  - bias_result.factors    → what each factor (SMT, SESSION, EMA, RSI) is saying
  - market_snapshot        → live price, EMAs, RSI, highs/lows

STEP 2 — Override or confirm the engine's result if needed.
  The engine is rules-based. You add judgment:
  - If SMT_DIVERGENCE fired but the score is low due to EMA conflict,
    you can override to the SMT direction — cite why.
  - If ALL factors agree, no override needed — use the engine's direction and confidence.
  - If the score is near 0 and factors are split, stay NEUTRAL.

STEP 3 — Call store_signal as the FINAL step.
  Use the direction and confidence from your analysis (engine output + your override).
  Reasoning must be 2–3 sentences citing the specific factors observed.

Decision shortcuts:
- SMT divergence present + session bias aligned → override EMA conflict, go with SMT.
- Liquidity sweep above HTF high + EMA bearish → SHORT.
- Liquidity sweep below HTF low + EMA bullish → LONG.
- score >= 0.7 → use engine confidence directly.
- score between 0.4–0.7 → cite the limiting factor in reasoning.

Never skip store_signal.\
"""


# ── Tool definitions ───────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_market_data",
        "description": (
            "Fetch a live price snapshot for a symbol. Returns current price, "
            "EMA20, EMA50, RSI14, daily high/low, period high/low, volume, "
            "EMA bias label, and the last 5 closes. Always call this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol to fetch, e.g. 'NQ', 'ES', 'GC', 'DXY'.",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_indicator_signals",
        "description": (
            "Read the 10 most recent indicator rows for a symbol from the database. "
            "Each row has: indicator_name, signal_value, bias (LONG/SHORT/NEUTRAL), "
            "extra_data (optional JSON), and timestamp. "
            "Use this to check SMT divergence, session bias, and custom indicator outputs. "
            "Always call this before get_market_data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol to query, e.g. 'NQ'.",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "compute_bias",
        "description": (
            "Run the BiasEngine on a symbol: fetches live market data AND reads indicator "
            "signals from DB, then returns a scored directional bias with per-factor breakdown. "
            "Use this as a fast sanity-check before calling store_signal. "
            "The result includes: direction, confidence (0–100), score (-1..+1), and each "
            "contributing factor (SMT_DIVERGENCE, SESSION_BIAS, EMA_STRUCTURE, RSI_CONTEXT)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol to score, e.g. 'NQ'.",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "store_signal",
        "description": (
            "Persist the final trading signal to the database. "
            "Call ONCE, as the last step, after analysis is complete. "
            "Do not call this speculatively — only when the conclusion is firm."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol analyzed, e.g. 'NQ'.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["LONG", "SHORT", "NEUTRAL"],
                    "description": "Directional bias.",
                },
                "confidence": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Confidence score 0–100 based on confluence strength.",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "2–3 sentence explanation citing specific confluence factors: "
                        "which indicators fired, SMT status, EMA structure, session context."
                    ),
                },
            },
            "required": ["symbol", "direction", "confidence", "reasoning"],
        },
    },
]


# ── Tool execution ─────────────────────────────────────────────────

def _execute_tool(name: str, tool_input: dict[str, Any], db: Session) -> Any:
    """Dispatch a tool call and return a JSON-serialisable result."""

    if name == "get_market_data":
        symbol = tool_input["symbol"].upper()
        logger.info("[tool] get_market_data symbol=%s", symbol)
        return get_market_snapshot(symbol)

    elif name == "get_indicator_signals":
        symbol = tool_input["symbol"].upper()
        logger.info("[tool] get_indicator_signals symbol=%s", symbol)
        rows = (
            db.query(IndicatorInput)
            .filter(IndicatorInput.symbol == symbol)
            .order_by(IndicatorInput.created_at.desc())
            .limit(10)
            .all()
        )
        if not rows:
            return {
                "symbol": symbol,
                "signals": [],
                "note": "No indicator data in DB for this symbol yet.",
            }
        return {
            "symbol": symbol,
            "count": len(rows),
            "signals": [
                {
                    "indicator_name": r.indicator_name,
                    "signal_value": r.signal_value,
                    "bias": r.bias,
                    "extra_data": r.extra_data,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }

    elif name == "compute_bias":
        symbol = tool_input["symbol"].upper()
        logger.info("[tool] compute_bias symbol=%s", symbol)

        # Fetch live snapshot
        snapshot = get_market_snapshot(symbol)

        # Read indicator signals from DB
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
        return {
            "symbol": symbol,
            "bias_result": result.summary(),
            "market_snapshot": snapshot,
        }

    elif name == "store_signal":
        # Agent returns confidence as 0–100 int; model stores 0.0–1.0 float
        confidence_normalized = float(tool_input["confidence"]) / 100.0
        symbol = tool_input["symbol"].upper()

        signal = Signal(
            symbol=symbol,
            direction=tool_input["direction"],
            confidence=confidence_normalized,
            reasoning=tool_input["reasoning"],
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)

        logger.info(
            "[tool] store_signal id=%s symbol=%s dir=%s conf=%.2f",
            signal.id, signal.symbol, signal.direction, signal.confidence,
        )
        return {
            "stored": True,
            "signal_id": signal.id,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "confidence": signal.confidence,  # 0.0–1.0
            "reasoning": signal.reasoning,
            "created_at": signal.created_at.isoformat(),
        }

    raise ValueError(f"Unknown tool: {name}")


# ── Agent loop ─────────────────────────────────────────────────────

def run_agent(query: str, db: Session, max_iterations: int = 10) -> dict:
    """
    Run the Claude tool-use agent loop.

    Parameters
    ----------
    query : str
        Natural language prompt, e.g. "Analyze NQ" or "What's the bias on ES today?"
    db : Session
        SQLAlchemy session — used by get_indicator_signals and store_signal.
    max_iterations : int
        Safety cap on the number of API round-trips (default 10).

    Returns
    -------
    dict
        The stored signal dict from store_signal, including signal_id.

    Raises
    ------
    RuntimeError
        If the agent exhausts iterations without calling store_signal.
    """
    messages: list[dict] = [{"role": "user", "content": query}]
    stored_signal: dict | None = None

    for iteration in range(max_iterations):
        logger.debug("[agent] iteration %d/%d", iteration + 1, max_iterations)

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        logger.debug("[agent] stop_reason=%s", response.stop_reason)

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": response.content})

        # No tool calls — agent finished without storing
        if response.stop_reason == "end_turn":
            logger.warning("[agent] end_turn without store_signal call")
            break

        # Process all tool_use blocks in this turn
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            logger.info("[agent] calling tool=%s input=%s", block.name, block.input)

            try:
                result = _execute_tool(block.name, block.input, db)
                if block.name == "store_signal":
                    stored_signal = result

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            except Exception as exc:
                logger.error("[agent] tool=%s error=%s", block.name, exc)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({"error": str(exc)}),
                    "is_error": True,
                })

        # Feed tool results back
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        # Signal stored — we're done
        if stored_signal is not None:
            break

    if stored_signal is None:
        raise RuntimeError(
            f"Agent completed {max_iterations} iterations without calling store_signal. "
            "Check logs for tool errors or prompt issues."
        )

    return stored_signal
