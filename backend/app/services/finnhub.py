"""Finnhub.io search for Canadian listings.

Free tier: 60 calls/minute, no day cap. Get a key at https://finnhub.io —
sign up with email, copy the API key from the dashboard, set it as
FINNHUB_API_KEY in Render.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

SEARCH_URL = "https://finnhub.io/api/v1/search"

# Canadian Yahoo/Finnhub symbol suffixes we want to surface.
CA_SUFFIXES = (".TO", ".V", ".CN", ".NE")
EXCHANGE_LABELS = {
    ".TO": "TSX",
    ".V":  "TSXV",
    ".CN": "CSE",
    ".NE": "NEO",
}


def _exchange_for(symbol: str) -> str | None:
    for suffix, label in EXCHANGE_LABELS.items():
        if symbol.endswith(suffix):
            return label
    return None


def _normalize(row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = (row.get("symbol") or row.get("displaySymbol") or "").strip()
    if not symbol or not any(symbol.endswith(s) for s in CA_SUFFIXES):
        return None
    return {
        "ticker": symbol,
        "name": (row.get("description") or symbol).title() if row.get("description", "").isupper() else (row.get("description") or symbol),
        "exchange": _exchange_for(symbol),
        "quote_type": row.get("type"),
        "sector": None,
        "industry": None,
    }


async def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    settings = get_settings()
    if not settings.finnhub_api_key:
        logger.warning("FINNHUB_API_KEY is not set — search returns empty.")
        return []

    params = {"q": q, "token": settings.finnhub_api_key}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Finnhub search failed for %r: %s", q, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in data.get("result") or []:
        norm = _normalize(row)
        if norm is None:
            continue
        out.append(norm)
        if len(out) >= limit:
            break
    return out
