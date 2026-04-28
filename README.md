# Trading Signal Agent

A FastAPI service that uses Claude AI as an autonomous trading analyst. Send a symbol, get back a structured LONG/SHORT/NEUTRAL signal — grounded in ICT/Smart Money logic, not vibes.

The agent doesn't just call an LLM with a prompt. It runs a tool-use loop: it pulls indicator signals from your database (TradingView webhooks, NinjaTrader, or manual input), fetches live market data, and applies ICT confluence rules before committing a signal.

---

## Architecture

```
TradingView / NinjaTrader
         │
         │  POST /api/v1/indicator
         ▼
┌─────────────────────────────────────────────────┐
│                   FastAPI App                   │
│                                                 │
│  POST /api/v1/analyze/{symbol}                  │
│         │                                       │
│         ▼                                       │
│  ┌─────────────────────────────────────────┐    │
│  │           Claude Agent Loop             │    │
│  │                                         │    │
│  │  1. get_indicator_signals(symbol)       │    │
│  │       └─ reads DB → SMT, session bias  │    │
│  │                                         │    │
│  │  2. get_market_data(symbol)             │    │
│  │       └─ yfinance → price, EMA, RSI    │    │
│  │                                         │    │
│  │  3. Claude reasons with ICT logic       │    │
│  │       └─ SMT divergence                │    │
│  │       └─ session bias                  │    │
│  │       └─ EMA structure                 │    │
│  │                                         │    │
│  │  4. store_signal(direction, conf, ...)  │    │
│  └─────────────────────────────────────────┘    │
│         │                                       │
│         ▼                                       │
│    PostgreSQL DB                                │
│    ├── signals          (agent output)          │
│    └── indicator_inputs (external feed)         │
└─────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111 + Uvicorn |
| AI Agent | Anthropic Claude (`claude-opus-4-6`) |
| Database | PostgreSQL + SQLAlchemy 2.0 + Alembic |
| Market Data | yfinance (price, EMA, RSI) |
| Validation | Pydantic v2 |
| Config | pydantic-settings + `.env` |

---

## Supported Symbols

| Category | Symbols |
|---|---|
| Equity Futures | `NQ`, `ES`, `YM`, `RTY` |
| Dollar Index | `DXY` |
| FX Futures | `6E`, `6B`, `6J`, `6A`, `6C` |
| Commodities | `GC`, `CL`, `SI` |
| Stocks / ETFs | Any yfinance-supported ticker |

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (local or Docker)
- Anthropic API key

### 1. Clone & install

```bash
git clone https://github.com/your-username/trading-signal-agent.git
cd trading-signal-agent

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://user:password@localhost:5432/trading_signals
APP_ENV=development
APP_PORT=8000
LOG_LEVEL=info
```

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`

---

## API Endpoints

### `POST /api/v1/analyze/{symbol}`

Triggers the Claude agent. The agent fetches indicator signals and market data autonomously, reasons using ICT logic, and returns a stored signal.

**Request**
```bash
curl -X POST http://localhost:8000/api/v1/analyze/NQ
```

**Response** `201 Created`
```json
{
  "signal_id": 42,
  "symbol": "NQ",
  "direction": "LONG",
  "confidence": 0.78,
  "reasoning": "SMT divergence confirmed between NQ and ES with NQ showing relative strength. NY kill zone is active with bullish session bias from indicator feed. EMA20 > EMA50 with price holding above both EMAs supports continuation.",
  "created_at": "2026-04-28T09:45:12.000Z",
  "stored": true
}
```

---

### `GET /api/v1/signals/{symbol}?limit=10`

Returns signal history for a symbol, most recent first.

**Request**
```bash
curl http://localhost:8000/api/v1/signals/NQ?limit=5
```

**Response** `200 OK`
```json
[
  {
    "id": 42,
    "symbol": "NQ",
    "direction": "LONG",
    "confidence": 0.78,
    "reasoning": "SMT divergence confirmed between NQ and ES...",
    "created_at": "2026-04-28T09:45:12.000Z"
  },
  {
    "id": 39,
    "symbol": "NQ",
    "direction": "NEUTRAL",
    "confidence": 0.35,
    "reasoning": "Conflicting signals: bullish EMA structure but bearish session bias and no SMT confirmation.",
    "created_at": "2026-04-28T07:30:01.000Z"
  }
]
```

---

### `GET /api/v1/signals/latest`

Returns the single most recent signal for every symbol in the database.

**Request**
```bash
curl http://localhost:8000/api/v1/signals/latest
```

**Response** `200 OK`
```json
[
  {
    "id": 42,
    "symbol": "NQ",
    "direction": "LONG",
    "confidence": 0.78,
    "reasoning": "SMT divergence confirmed between NQ and ES...",
    "created_at": "2026-04-28T09:45:12.000Z"
  },
  {
    "id": 41,
    "symbol": "ES",
    "direction": "SHORT",
    "confidence": 0.65,
    "reasoning": "ES showing weakness relative to NQ with bearish EMA stack and NY session bias aligning short.",
    "created_at": "2026-04-28T09:44:58.000Z"
  }
]
```

---

### `POST /api/v1/indicator`

Ingests an indicator signal from TradingView, NinjaTrader, or any custom source. These signals are what the agent reads during analysis.

**Request**
```bash
curl -X POST http://localhost:8000/api/v1/indicator \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NQ",
    "indicator_name": "SMT_Divergence",
    "signal_value": 1.0,
    "bias": "LONG",
    "extra_data": {
      "correlated_symbol": "ES",
      "session": "NY",
      "sweep_detected": true
    }
  }'
```

**Response** `201 Created`
```json
{
  "id": 17,
  "symbol": "NQ",
  "indicator_name": "SMT_Divergence",
  "signal_value": 1.0,
  "bias": "LONG",
  "extra_data": {
    "correlated_symbol": "ES",
    "session": "NY",
    "sweep_detected": true
  },
  "created_at": "2026-04-28T09:44:30.000Z"
}
```

---

### `GET /health`

```bash
curl http://localhost:8000/health
# {"status": "ok", "env": "development"}
```

---

## How Indicator Signals Feed the Agent

The agent's decision logic follows a strict priority stack:

```
SMT Divergence  ──▶  highest weight
      │
Session Bias    ──▶  amplifies direction
      │
EMA Structure   ──▶  structural confirmation
      │
    Signal
```

When you call `POST /api/v1/analyze/NQ`, the agent:

1. **Reads your indicator DB** — looks at the 10 most recent rows for NQ. If `SMT_Divergence` is present with `bias: LONG` and session is NY kill zone, that's the primary signal.

2. **Fetches live price data** — yfinance pulls 5 days of hourly bars. Calculates EMA20, EMA50, RSI14, daily high/low, and period extremes.

3. **Applies confluence rules** — if indicators and structure agree, confidence goes 70–90. If one is mixed, 40–65. If contradictory, NEUTRAL ≤ 40.

4. **Stores and returns** — the signal is persisted with full reasoning before the HTTP response is sent.

### Example TradingView Webhook

Point your Pine Script `alertcondition` webhook at `POST /api/v1/indicator`:

```json
{
  "symbol": "{{ticker}}",
  "indicator_name": "SessionBias",
  "signal_value": 1,
  "bias": "LONG",
  "extra_data": {
    "session": "{{timenow}}",
    "bar_close": {{close}}
  }
}
```

---

## Project Structure

```
trading-signal-agent/
├── app/
│   ├── agents/
│   │   └── claude_agent.py      # Tool-use loop + ICT system prompt
│   ├── api/
│   │   └── routes/
│   │       ├── analyze.py       # POST /analyze/{symbol}
│   │       ├── signals.py       # GET /signals/{symbol}, /signals/latest
│   │       └── indicator.py     # POST /indicator
│   ├── core/
│   │   └── config.py            # pydantic-settings
│   ├── db/
│   │   └── session.py           # SQLAlchemy engine + session
│   ├── models/
│   │   ├── signal.py            # Signal ORM model
│   │   └── indicator_input.py   # IndicatorInput ORM model
│   ├── schemas/
│   │   ├── signal.py            # SignalResponse, AnalyzeResponse
│   │   └── indicator.py         # IndicatorInputCreate, IndicatorInputResponse
│   ├── services/
│   │   └── market_data.py       # yfinance wrapper + technical calculations
│   └── main.py                  # FastAPI app + router registration
├── alembic/                     # DB migrations
├── requirements.txt
└── .env.example
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `APP_ENV` | — | `development` or `production` (default: `development`) |
| `APP_PORT` | — | Port to bind (default: `8000`) |
| `LOG_LEVEL` | — | `debug`, `info`, `warning` (default: `info`) |
