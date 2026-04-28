"""
Bias Decision Engine — Step 6

Separates the bias-scoring logic from the Claude agent loop so it can be:
  - unit tested independently
  - called by the agent via a tool
  - called directly by other services (e.g. a scheduled scanner)

Architecture
------------
The engine takes two inputs:
  1. market_snapshot  — output of get_market_snapshot()
  2. indicator_signals — list of IndicatorInput dicts (from DB)

And returns a BiasResult with:
  direction   : "LONG" | "SHORT" | "NEUTRAL"
  confidence  : int (0–100)
  score       : float (-1.0 to +1.0)  raw weighted score before thresholding
  factors     : dict of each contributing factor and its vote

Scoring logic (ICT / SMC priority stack)
-----------------------------------------
LAYER 1 — Structural indicators from DB (weight = 2.0 each)
  SMT_DIVERGENCE        → bias vote as stored
  SESSION_BIAS          → bias vote as stored
  LIQUIDITY_SWEEP       → bias vote as stored
  Any other indicator   → weight 1.0

LAYER 2 — EMA structure from market snapshot (weight = 1.0)
  price > EMA20 > EMA50  → LONG
  price < EMA20 < EMA50  → SHORT
  mixed                  → NEUTRAL (contributes 0)

LAYER 3 — RSI context (weight = 0.5)
  RSI > 70 in a LONG setup   → weakens (subtract 0.25)
  RSI < 30 in a SHORT setup  → weakens (subtract 0.25)
  Otherwise neutral

Confluence gate
  score >= +0.4  → LONG
  score <= -0.4  → SHORT
  between        → NEUTRAL
  |score| mapped linearly to confidence 40–90
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ── Types ─────────────────────────────────────────────────────────

Direction = Literal["LONG", "SHORT", "NEUTRAL"]

# High-priority indicator names (weight 2.0 vs default 1.0)
HIGH_PRIORITY_INDICATORS = {"SMT_DIVERGENCE", "SESSION_BIAS", "LIQUIDITY_SWEEP"}

# Confidence thresholds
STRONG_THRESHOLD = 0.70   # |score| ≥ this → confidence 80–90
MODERATE_THRESHOLD = 0.40  # |score| ≥ this → LONG/SHORT, confidence 40–79


@dataclass
class BiasFactor:
    name: str
    vote: Direction          # what this factor is saying
    weight: float            # how much it counts
    contribution: float      # +weight (LONG), -weight (SHORT), 0 (NEUTRAL)
    note: str = ""


@dataclass
class BiasResult:
    direction: Direction
    confidence: int          # 0–100
    score: float             # raw weighted score, -1..+1 (approx)
    factors: list[BiasFactor] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "score": round(self.score, 3),
            "factors": [
                {
                    "name": f.name,
                    "vote": f.vote,
                    "weight": f.weight,
                    "contribution": f.contribution,
                    "note": f.note,
                }
                for f in self.factors
            ],
        }


# ── Core scoring ──────────────────────────────────────────────────

def _vote_to_contribution(vote: Direction, weight: float) -> float:
    if vote == "LONG":
        return +weight
    if vote == "SHORT":
        return -weight
    return 0.0


def _map_score_to_confidence(score: float) -> int:
    """
    Map absolute score to a confidence integer.
    score = 0.0  → 30  (NEUTRAL baseline)
    score = 0.40 → 50
    score = 0.70 → 75
    score = 1.0+ → 90
    """
    abs_score = abs(score)
    if abs_score >= 1.0:
        return 90
    if abs_score >= STRONG_THRESHOLD:
        # 0.70 → 75, 1.0 → 90
        return int(75 + (abs_score - STRONG_THRESHOLD) / (1.0 - STRONG_THRESHOLD) * 15)
    if abs_score >= MODERATE_THRESHOLD:
        # 0.40 → 50, 0.70 → 75
        return int(50 + (abs_score - MODERATE_THRESHOLD) / (STRONG_THRESHOLD - MODERATE_THRESHOLD) * 25)
    # 0 → 30, 0.40 → 50
    return int(30 + abs_score / MODERATE_THRESHOLD * 20)


def score_bias(
    market_snapshot: dict,
    indicator_signals: list[dict],
) -> BiasResult:
    """
    Compute directional bias from market snapshot + indicator rows.

    Parameters
    ----------
    market_snapshot : dict
        Output of get_market_snapshot() — must contain:
        current_price, ema20, ema50, ema_bias, rsi14
    indicator_signals : list[dict]
        Each dict must have keys: indicator_name, bias (LONG/SHORT/NEUTRAL),
        signal_value, extra_data (optional)

    Returns
    -------
    BiasResult
    """
    factors: list[BiasFactor] = []
    total_weight = 0.0
    weighted_sum = 0.0

    # ── LAYER 1: Indicator signals ────────────────────────────────
    # Deduplicate: if the same indicator fires multiple times,
    # use the most recent one (list assumed newest-first from DB).
    seen: set[str] = set()
    for row in indicator_signals:
        name = row.get("indicator_name", "UNKNOWN").upper()
        bias = row.get("bias", "NEUTRAL").upper()

        if name in seen:
            continue
        seen.add(name)

        if bias not in ("LONG", "SHORT", "NEUTRAL"):
            bias = "NEUTRAL"

        weight = 2.0 if name in HIGH_PRIORITY_INDICATORS else 1.0
        contribution = _vote_to_contribution(bias, weight)

        note = ""
        if name == "SMT_DIVERGENCE" and bias != "NEUTRAL":
            extra = row.get("extra_data") or {}
            corr = extra.get("corr_symbol", "")
            note = f"corr={corr}" if corr else ""

        factors.append(BiasFactor(
            name=name, vote=bias, weight=weight,
            contribution=contribution, note=note
        ))
        weighted_sum += contribution
        total_weight += weight

    # ── LAYER 2: EMA structure ────────────────────────────────────
    ema_bias: str = market_snapshot.get("ema_bias", "MIXED").upper()
    if ema_bias == "BULLISH":
        ema_vote: Direction = "LONG"
    elif ema_bias == "BEARISH":
        ema_vote = "SHORT"
    else:
        ema_vote = "NEUTRAL"

    ema_weight = 1.0
    ema_contribution = _vote_to_contribution(ema_vote, ema_weight)
    ema20 = market_snapshot.get("ema20", 0)
    ema50 = market_snapshot.get("ema50", 0)
    factors.append(BiasFactor(
        name="EMA_STRUCTURE", vote=ema_vote, weight=ema_weight,
        contribution=ema_contribution,
        note=f"EMA20={ema20:.1f} EMA50={ema50:.1f}"
    ))
    weighted_sum += ema_contribution
    total_weight += ema_weight

    # ── LAYER 3: RSI context ──────────────────────────────────────
    rsi = market_snapshot.get("rsi14")
    rsi_contribution = 0.0
    rsi_note = ""
    rsi_vote: Direction = "NEUTRAL"

    if rsi is not None:
        if rsi > 70:
            # Overbought — weakens any LONG signals
            rsi_contribution = -0.25
            rsi_vote = "SHORT"
            rsi_note = f"RSI={rsi:.1f} overbought — dampening LONG"
        elif rsi < 30:
            # Oversold — weakens any SHORT signals
            rsi_contribution = +0.25
            rsi_vote = "LONG"
            rsi_note = f"RSI={rsi:.1f} oversold — dampening SHORT"
        else:
            rsi_note = f"RSI={rsi:.1f} neutral zone"

    rsi_weight = 0.5
    factors.append(BiasFactor(
        name="RSI_CONTEXT", vote=rsi_vote, weight=rsi_weight,
        contribution=rsi_contribution, note=rsi_note
    ))
    weighted_sum += rsi_contribution
    total_weight += rsi_weight

    # ── Normalize score ───────────────────────────────────────────
    # Normalize to -1..+1 range based on max possible weight
    score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # ── Confluence gate ───────────────────────────────────────────
    if score >= MODERATE_THRESHOLD:
        direction: Direction = "LONG"
    elif score <= -MODERATE_THRESHOLD:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    confidence = _map_score_to_confidence(score)

    return BiasResult(
        direction=direction,
        confidence=confidence,
        score=score,
        factors=factors,
    )
