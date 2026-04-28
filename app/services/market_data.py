"""
Market data fetcher — yfinance wrapper with technical overlays.

Covers futures (NQ, ES, YM), forex proxies (DXY, 6E, 6B),
and any stock/ETF symbol yfinance supports.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Symbol alias map ──────────────────────────────────────────────
# Human-friendly names → yfinance tickers.
# Extend this dict as needed; unknown symbols pass through unchanged.

SYMBOL_ALIASES: dict[str, str] = {
    # CME E-mini futures
    "NQ": "NQ=F",
    "ES": "ES=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
    # Dollar index
    "DXY": "DX-Y.NYB",
    # CME FX futures
    "6E": "6E=F",   # Euro FX
    "6B": "6B=F",   # British Pound
    "6J": "6J=F",   # Japanese Yen
    "6A": "6A=F",   # Australian Dollar
    "6C": "6C=F",   # Canadian Dollar
    # Commodities
    "GC": "GC=F",   # Gold
    "CL": "CL=F",   # Crude Oil
    "SI": "SI=F",   # Silver
}


def resolve_symbol(symbol: str) -> str:
    """Map a human-friendly symbol to its yfinance ticker."""
    key = symbol.upper().strip()
    return SYMBOL_ALIASES.get(key, key)


# ── OHLCV fetch ───────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    period: str = "1d",
    interval: str = "1h",
) -> pd.DataFrame:
    """
    Return a clean OHLCV DataFrame for *symbol*.

    Parameters
    ----------
    symbol : str
        Human-friendly (e.g. "NQ") or raw yfinance ticker.
    period : str
        Look-back window — "1d", "5d", "1mo", etc.
    interval : str
        Bar size — "1m", "5m", "15m", "1h", "1d", etc.

    Returns
    -------
    pd.DataFrame
        Columns: Open, High, Low, Close, Volume (tz-naive UTC index).

    Raises
    ------
    ValueError
        If yfinance returns no data.
    """
    yf_symbol = resolve_symbol(symbol)
    ticker = yf.Ticker(yf_symbol)
    df: pd.DataFrame = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(
            f"No data returned for {symbol} (yfinance ticker: {yf_symbol}). "
            "Check symbol validity and market hours."
        )

    # Normalize: drop Dividends/Stock Splits if present, keep OHLCV
    keep_cols = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()

    # Strip timezone for downstream consistency
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)

    return df


# ── Technical calculations ────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical columns to an OHLCV DataFrame **in place** and return it.

    Added columns
    -------------
    EMA20, EMA50   — Exponential moving averages on Close.
    RSI14          — 14-period RSI on Close.
    DailyHigh      — Rolling calendar-day high (useful on intraday frames).
    DailyLow       — Rolling calendar-day low.
    """
    df = df.copy()

    df["EMA20"] = _ema(df["Close"], 20)
    df["EMA50"] = _ema(df["Close"], 50)
    df["RSI14"] = _rsi(df["Close"], 14)

    # Daily high/low — group by date portion of the index
    df["_date"] = df.index.date
    daily_hl = df.groupby("_date").agg(
        DailyHigh=("High", "max"),
        DailyLow=("Low", "min"),
    )
    df = df.join(daily_hl, on="_date")
    df.drop(columns=["_date"], inplace=True)

    return df


# ── LLM-ready snapshot ───────────────────────────────────────────

def get_market_snapshot(
    symbol: str,
    period: str = "5d",
    interval: str = "1h",
) -> dict:
    """
    Return a compact dict summary ready to pass into an LLM prompt.

    Fetches data, computes technicals, and distils the latest state
    plus recent context into a flat, serialisable dictionary.
    """
    raw_symbol = symbol.upper().strip()
    df = fetch_ohlcv(raw_symbol, period=period, interval=interval)
    df = calculate_technicals(df)

    latest = df.iloc[-1]
    prev_close = df["Close"].iloc[-2] if len(df) > 1 else latest["Close"]
    change_pct = (float(latest["Close"]) - float(prev_close)) / float(prev_close) * 100

    # Determine EMA bias
    ema20 = float(latest["EMA20"])
    ema50 = float(latest["EMA50"])
    price = float(latest["Close"])

    if price > ema20 > ema50:
        ema_bias = "BULLISH"
    elif price < ema20 < ema50:
        ema_bias = "BEARISH"
    else:
        ema_bias = "MIXED"

    rsi = float(latest["RSI14"]) if pd.notna(latest["RSI14"]) else None

    return {
        "symbol": raw_symbol,
        "yf_ticker": resolve_symbol(raw_symbol),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "bar_interval": interval,
        "lookback_period": period,
        # Price
        "current_price": round(price, 5),
        "change_pct": round(change_pct, 2),
        "daily_high": round(float(latest["DailyHigh"]), 5),
        "daily_low": round(float(latest["DailyLow"]), 5),
        "period_high": round(float(df["High"].max()), 5),
        "period_low": round(float(df["Low"].min()), 5),
        # Volume
        "volume_latest": int(latest["Volume"]),
        "volume_avg": int(df["Volume"].mean()),
        # Technicals
        "ema20": round(ema20, 5),
        "ema50": round(ema50, 5),
        "ema_bias": ema_bias,
        "rsi14": round(rsi, 2) if rsi is not None else None,
        # Recent bars (last 5) for context
        "recent_closes": [
            round(float(c), 5) for c in df["Close"].tail(5).tolist()
        ],
    }


# ── Backward compatibility ────────────────────────────────────────
# The existing /signals/generate/{symbol} route calls this function.

def fetch_market_summary(
    symbol: str,
    period: str = "5d",
    interval: str = "1h",
) -> dict:
    """Legacy wrapper — delegates to get_market_snapshot."""
    return get_market_snapshot(symbol, period=period, interval=interval)
