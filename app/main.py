from fastapi import FastAPI
from app.api.routes import signals
from app.core.config import settings

app = FastAPI(
    title="Trading Signal Agent",
    version="0.1.0",
    description="Claude-powered trading signal generation API",
)

app.include_router(signals.router, prefix="/signals", tags=["signals"])


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.APP_ENV}
