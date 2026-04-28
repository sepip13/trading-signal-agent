import yfinance as yf
import pandas as pd


def fetch_market_summary(symbol: str, period: str = "5d", interval: str = "1h") -> dict:
    ticker = yf.Ticker(symbol)
    df: pd.DataFrame = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    latest = df.iloc[-1]
    prev_close = df["Close"].iloc[-2] if len(df) > 1 else latest["Close"]

    return {
        "symbol": symbol,
        "current_price": round(float(latest["Close"]), 4),
        "change_pct": round((float(latest["Close"]) - float(prev_close)) / float(prev_close) * 100, 2),
        "volume": int(latest["Volume"]),
        "high_5d": round(float(df["High"].max()), 4),
        "low_5d": round(float(df["Low"].min()), 4),
        "avg_volume_5d": int(df["Volume"].mean()),
    }
