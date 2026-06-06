"""Thin client for SEDAR+ (https://www.sedarplus.ca).

SEDAR+ exposes no documented public API. This module talks to the same
internal JSON endpoints the official web UI uses. They are unstable by
nature — if SEDAR+ ships a UI redesign these may break and need patching.

Design goals:
  * Polite (low rate, identifies itself, retries with backoff)
  * Easy to debug (raw responses logged at DEBUG level)
  * Resilient to schema drift (treat fields as optional and tolerate
    missing/renamed keys)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

class SedarMaintenanceError(RuntimeError):
    """Raised when SEDAR+ responds with its maintenance page."""


BASE_URL = "https://www.sedarplus.ca"
USER_AGENT = (
    "SedarWatchlist/0.1 (+https://github.com/giulianomana-hash/canadian-microcaps) "
    "personal research tool"
)
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Common search endpoint used by the SEDAR+ search UI.
SEARCH_PATH = "/csa-party/service/CommonSearch/getSearchResults"
# Filing list endpoint, scoped to a party (company) profile.
FILINGS_PATH = "/csa-party/service/Filing/getFilingList"


@dataclass
class CompanyHit:
    profile_id: str
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    jurisdiction: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sedar_profile_id": self.profile_id,
            "name": self.name,
            "ticker": self.ticker,
            "exchange": self.exchange,
            "jurisdiction": self.jurisdiction,
        }


@dataclass
class FilingHit:
    filing_id: str
    filing_type: str
    filing_date: date
    url: str
    title: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sedar_filing_id": self.filing_id,
            "filing_type": self.filing_type,
            "filing_date": self.filing_date.isoformat(),
            "url": self.url,
            "title": self.title,
        }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=DEFAULT_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-CA,en;q=0.9",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/landingpage/",
        },
        follow_redirects=True,
    )


def _coerce_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _pick(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


async def search_companies(query: str, limit: int = 15) -> list[CompanyHit]:
    """Search SEDAR+ by company name or ticker.

    Returns up to `limit` hits, empty list on no results or transient error.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []

    body = {
        "searchText": q,
        "type": "PARTY",   # restrict to issuer/company profiles
        "pageNumber": 1,
        "pageSize": limit,
    }
    try:
        async with _client() as client:
            resp = await client.post(SEARCH_PATH, json=body)
            resp.raise_for_status()
            if "maintenance" in (resp.text[:2000].lower()) and "sedar" in (resp.text[:2000].lower()):
                raise SedarMaintenanceError("SEDAR+ is in maintenance mode.")
            data = resp.json()
    except SedarMaintenanceError:
        raise
    except Exception as exc:
        logger.warning("SEDAR+ search failed for %r: %s", q, exc)
        return []

    logger.debug("SEDAR+ search %r raw: %s", q, data)

    rows = (
        data.get("results")
        or data.get("rows")
        or data.get("data")
        or data.get("items")
        or []
    )

    hits: list[CompanyHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        profile = _pick(row, "profileNumber", "partyId", "id", "profileId")
        name = _pick(row, "partyName", "companyName", "name", "issuerName")
        if not profile or not name:
            continue
        hits.append(
            CompanyHit(
                profile_id=str(profile),
                name=str(name),
                ticker=(_pick(row, "tickerSymbol", "ticker", "symbol") or None),
                exchange=(_pick(row, "exchange", "marketplace") or None),
                jurisdiction=(_pick(row, "jurisdiction", "homeJurisdiction") or None),
            )
        )
        if len(hits) >= limit:
            break
    return hits


async def list_filings(profile_id: str, limit: int = 25) -> list[FilingHit]:
    """Fetch recent filings for a single SEDAR+ profile (company)."""
    body = {
        "partyId": profile_id,
        "pageNumber": 1,
        "pageSize": limit,
        "sortField": "filingDate",
        "sortOrder": "DESC",
    }
    try:
        async with _client() as client:
            resp = await client.post(FILINGS_PATH, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("SEDAR+ filings fetch failed for %s: %s", profile_id, exc)
        return []

    logger.debug("SEDAR+ filings %s raw: %s", profile_id, data)

    rows = (
        data.get("results")
        or data.get("rows")
        or data.get("data")
        or data.get("items")
        or []
    )

    out: list[FilingHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        filing_id = _pick(row, "filingId", "submissionId", "id")
        filing_type = _pick(row, "filingType", "documentType", "type", "category")
        filing_date = _coerce_date(_pick(row, "filingDate", "submittedDate", "date"))
        url = _pick(row, "url", "documentUrl", "viewUrl")
        if url and url.startswith("/"):
            url = f"{BASE_URL}{url}"
        if not (filing_id and filing_type and filing_date and url):
            continue
        out.append(
            FilingHit(
                filing_id=str(filing_id),
                filing_type=str(filing_type),
                filing_date=filing_date,
                url=str(url),
                title=(_pick(row, "title", "subject", "description") or None),
            )
        )
    return out


async def list_filings_for_many(
    profile_ids: list[str], per_company_limit: int = 25, delay_seconds: float = 1.5
) -> dict[str, list[FilingHit]]:
    """Sequentially fetch filings for a batch of profiles, rate-limited."""
    out: dict[str, list[FilingHit]] = {}
    for i, pid in enumerate(profile_ids):
        if i:
            await asyncio.sleep(delay_seconds)
        out[pid] = await list_filings(pid, limit=per_company_limit)
    return out


# ---------- diagnostics ----------

_DIAG_CANDIDATES = [
    # (label, method, path, payload-or-querystring)
    ("post_CommonSearch_getSearchResults", "POST", "/csa-party/service/CommonSearch/getSearchResults",
     {"searchText": "{q}", "type": "ALL", "pageNumber": 1, "pageSize": 5}),
    ("post_CommonSearch_PARTY", "POST", "/csa-party/service/CommonSearch/getSearchResults",
     {"searchText": "{q}", "type": "PARTY", "pageNumber": 1, "pageSize": 5}),
    ("get_csa-party_search", "GET", "/csa-party/search/?q={q}", None),
    ("get_landingpage_party", "GET", "/landingpage/party/?searchText={q}", None),
    ("post_party_search", "POST", "/csa-party/service/Party/search",
     {"searchText": "{q}", "pageNumber": 1, "pageSize": 5}),
    ("get_party_v1_search", "GET", "/api/v1/party/search?q={q}", None),
    ("get_root_search", "GET", "/?searchText={q}", None),
]


async def diagnose(query: str = "shopify") -> dict:
    """Hit each candidate endpoint once and report status + a body preview."""
    out: dict = {"query": query, "candidates": []}
    async with _client() as client:
        for label, method, path, payload in _DIAG_CANDIDATES:
            entry: dict = {"label": label, "method": method, "path": path}
            try:
                if method == "POST":
                    body = {k: (v.replace("{q}", query) if isinstance(v, str) else v) for k, v in (payload or {}).items()}
                    resp = await client.post(path, json=body)
                    entry["request_body"] = body
                else:
                    resp = await client.get(path.replace("{q}", query))
                entry["status"] = resp.status_code
                entry["content_type"] = resp.headers.get("content-type")
                text = resp.text or ""
                entry["body_preview"] = text[:600]
                entry["body_length"] = len(text)
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            out["candidates"].append(entry)
    return out
