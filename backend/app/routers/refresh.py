"""Ingest endpoint for scraped filings.

The Playwright scraper running in GitHub Actions POSTs to /api/filings/ingest
with whatever new filings it discovered. We dedupe, insert, and email a
summary via Resend.

The legacy /api/refresh endpoint is kept as a no-op for backwards
compatibility — it now simply reports the queue length.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from ..config import get_settings
from ..schemas import FilingsIngestPayload, IngestSummary, RefreshSummary
from ..services import notifications
from ..supabase_client import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ingest"])


def _check_auth(authorization: str | None) -> None:
    secret = get_settings().refresh_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="REFRESH_SECRET is not configured on the server.",
        )
    if authorization != f"Bearer {secret}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )


@router.post("/filings/ingest", response_model=IngestSummary)
async def ingest_filings(
    payload: FilingsIngestPayload,
    authorization: str | None = Header(default=None),
) -> IngestSummary:
    _check_auth(authorization)

    sb = get_supabase()
    received = len(payload.filings)
    if received == 0:
        return IngestSummary(received=0, inserted=0, email_sent=False)

    # Diff against already-seen filings by (sedar_profile_id, sedar_filing_id).
    pairs = {(f.sedar_profile_id or "", f.sedar_filing_id) for f in payload.filings}
    profile_ids = {pid for pid, _ in pairs if pid}
    seen: set[tuple[str, str]] = set()
    if profile_ids:
        existing = (
            sb.table("filings")
            .select("sedar_profile_id, sedar_filing_id")
            .in_("sedar_profile_id", list(profile_ids))
            .execute()
        )
        seen = {
            (row.get("sedar_profile_id") or "", row.get("sedar_filing_id"))
            for row in (existing.data or [])
            if row.get("sedar_filing_id")
        }

    new_rows = []
    for f in payload.filings:
        key = (f.sedar_profile_id or "", f.sedar_filing_id)
        if key in seen:
            continue
        new_rows.append(
            {
                "sedar_profile_id": f.sedar_profile_id,
                "sedar_filing_id": f.sedar_filing_id,
                "ticker": f.ticker,
                "filing_type": f.filing_type,
                "filing_date": f.filing_date.isoformat(),
                "url": f.url,
                "title": f.title,
                "source": f.source,
            }
        )

    inserted = 0
    if new_rows:
        try:
            resp = sb.table("filings").insert(new_rows).execute()
            inserted = len(resp.data or [])
        except Exception as exc:
            logger.warning("Bulk insert failed (%s); falling back to per-row.", exc)
            for row in new_rows:
                try:
                    sb.table("filings").insert(row).execute()
                    inserted += 1
                except Exception as inner:
                    logger.info("Skipping duplicate filing: %s", inner)

    email_sent = False
    if new_rows:
        email_sent = await notifications.send_new_filings_email(new_rows)

    return IngestSummary(received=received, inserted=inserted, email_sent=email_sent)


@router.get("/scrape-targets")
def scrape_targets(authorization: str | None = Header(default=None)) -> list[dict]:
    """Return one row per watched company that has a SEDAR+ URL or id, so the
    Playwright job knows what to scrape. Auth'd by REFRESH_SECRET.
    """
    _check_auth(authorization)
    sb = get_supabase()
    resp = (
        sb.table("watchlist")
        .select("sedar_profile_id, sedar_profile_url, ticker, name")
        .execute()
    )
    out = []
    seen = set()
    for row in resp.data or []:
        url = (row.get("sedar_profile_url") or "").strip()
        pid = (row.get("sedar_profile_id") or "").strip()
        if not url and not pid:
            continue
        key = url or pid
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "sedar_profile_id": pid or None,
                "sedar_profile_url": url or None,
                "ticker": row.get("ticker"),
                "name": row.get("name"),
            }
        )
    return out


@router.post("/refresh", response_model=RefreshSummary)
def refresh(authorization: str | None = Header(default=None)) -> RefreshSummary:
    """Legacy: with Imperva blocking server-side SEDAR+ access, the actual
    scraping happens in GitHub Actions. This endpoint just reports the current
    queue size for diagnostics.
    """
    _check_auth(authorization)
    sb = get_supabase()
    watch = (
        sb.table("watchlist")
        .select("sedar_profile_id, sedar_profile_url")
        .execute()
    )
    rows = watch.data or []
    pollable = sum(1 for r in rows if r.get("sedar_profile_url") or r.get("sedar_profile_id"))
    return RefreshSummary(companies_checked=pollable, new_filings=0, email_sent=False)
