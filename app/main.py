from fastapi import FastAPI

from app.api.routes import analyze, indicator, scan, signals
from app.core.config import settings

app = FastAPI(
    title="Trading Signal Agent",
    version="0.1.0",
    description="Claude-powered ICT/SMT trading signal generation API",
)

# ── Routes ─────────────────────────────────────────────────────────
# Order matters: more specific prefixes first.

app.include_router(
    analyze.router,
    prefix="/api/v1/analyze",
    tags=["analyze"],
)
app.include_router(
    signals.router,
    prefix="/api/v1/signals",
    tags=["signals"],
)
app.include_router(
    indicator.router,
    prefix="/api/v1/indicator",
    tags=["indicator-inputs"],
)
app.include_router(
    scan.router,
    prefix="/api/v1/scan",
    tags=["scan"],
)


# ── Health ─────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "env": settings.APP_ENV}
