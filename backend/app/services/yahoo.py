"""Lightweight wrapper over Yahoo Finance's unofficial search endpoint.

Public, no API key, used by yfinance and many other tools. We only call
the search route — no quote/financials calls — and filter to Canadian
listings (TSX / TSXV / CSE / NEO).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# Canonical Yahoo exchange codes for Canadian venues.
CA_EXCHANGES = {"TOR", "VAN", "CNQ", "NEO", "CSE"}
CA_SYMBOL_SUFFIXES = (".TO", ".V", ".CN", ".NE")

EXCHANGE_LABELS = {
    "TOR": "TSX",
    "VAN": "TSXV",
    "CNQ": "CSE",
    "CSE": "CSE",
    "NEO": "NEO",
}


def _is_canadian(quote: dict[str, Any]) -> bool:
    exch = quote.get("exchange")
    if exch in CA_EXCHANGES:
        return True
    sym = quote.get("symbol") or ""
    return any(sym.endswith(s) for s in CA_SYMBOL_SUFFIXES)


def _normalize(quote: dict[str, Any]) -> dict[str, Any]:
    sym = quote.get("symbol") or ""
    exch = quote.get("exchange")
    return {
        "ticker": sym,
        "name": quote.get("shortname") or quote.get("longname") or sym,
        "exchange": EXCHANGE_LABELS.get(exch, exch),
        "quote_type": quote.get("quoteType"),
        "sector": quote.get("sector"),
        "industry": quote.get("industry"),
    }


async def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    params = {
        "q": q,
        "quotesCount": 20,
        "newsCount": 0,
        "lang": "en-CA",
        "region": "CA",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Yahoo search failed for %r: %s", q, exc)
        return []

    quotes = data.get("quotes") or []
    out = []
    for quote in quotes:
        if quote.get("quoteType") != "EQUITY":
            continue
        if not _is_canadian(quote):
            continue
        out.append(_normalize(quote))
        if len(out) >= limit:
            break
    return out
