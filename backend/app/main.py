import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import filings, refresh, watchlist

logging.basicConfig(level=logging.INFO)

settings = get_settings()

app = FastAPI(
    title="SedarWatchlist API",
    description="Backend for tracking Canadian microcap companies and their SEDAR+ filings.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(watchlist.router)
app.include_router(filings.router)
app.include_router(refresh.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
