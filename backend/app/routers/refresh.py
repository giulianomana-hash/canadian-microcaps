"""Scheduled poller: pull recent filings from SEDAR+ for every watched
company, insert anything new into the `filings` table, and email a summary.

Triggered by an external scheduler (GitHub Actions cron). The endpoint is
authenticated by a shared bearer secret set in REFRESH_SECRET.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from ..config import get_settings
from ..schemas import RefreshSummary
from ..services import notifications, sedar_plus
from ..supabase_client import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["refresh"])


def _check_auth(authorization: str | None) -> None:
    secret = get_settings().refresh_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="REFRESH_SECRET is not configured on the server.",
        )
    expected = f"Bearer {secret}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )


@router.post("/refresh", response_model=RefreshSummary)
async def refresh(authorization: str | None = Header(default=None)) -> RefreshSummary:
    _check_auth(authorization)

    sb = get_supabase()

    # 1. Distinct SEDAR profiles currently on anyone's watchlist.
    watch_resp = (
        sb.table("watchlist")
        .select("sedar_profile_id, ticker, name")
        .not_.is_("sedar_profile_id", "null")
        .execute()
    )
    profiles: dict[str, dict] = {}
    for row in watch_resp.data or []:
        pid = row.get("sedar_profile_id")
        if pid and pid not in profiles:
            profiles[pid] = {"ticker": row.get("ticker"), "name": row.get("name")}

    if not profiles:
        return RefreshSummary(companies_checked=0, new_filings=0, email_sent=False)

    # 2. Existing filing ids per profile, to diff against.
    existing_resp = (
        sb.table("filings")
        .select("sedar_profile_id, sedar_filing_id")
        .in_("sedar_profile_id", list(profiles.keys()))
        .execute()
    )
    seen: dict[str, set[str]] = {}
    for row in existing_resp.data or []:
        pid = row.get("sedar_profile_id")
        fid = row.get("sedar_filing_id")
        if pid and fid:
            seen.setdefault(pid, set()).add(fid)

    # 3. Pull recent filings per profile, rate-limited.
    fresh = await sedar_plus.list_filings_for_many(list(profiles.keys()))

    # 4. Insert anything we haven't recorded.
    new_rows: list[dict] = []
    for pid, filings in fresh.items():
        meta = profiles.get(pid, {})
        for f in filings:
            if f.filing_id in seen.get(pid, set()):
                continue
            new_rows.append(
                {
                    "sedar_profile_id": pid,
                    "sedar_filing_id": f.filing_id,
                    "ticker": meta.get("ticker"),
                    "filing_type": f.filing_type,
                    "filing_date": f.filing_date.isoformat(),
                    "url": f.url,
                    "title": f.title,
                }
            )

    if new_rows:
        try:
            sb.table("filings").insert(new_rows).execute()
        except Exception as exc:
            # A unique-index race can still happen if two refreshes overlap.
            logger.warning("Bulk insert failed (%s); falling back to per-row.", exc)
            for row in new_rows:
                try:
                    sb.table("filings").insert(row).execute()
                except Exception as inner:
                    logger.info("Skipping duplicate filing: %s", inner)

    # 5. Email a summary if anything is new and email is configured.
    email_sent = False
    if new_rows:
        # Decorate rows with company name for the email body.
        decorated = []
        for row in new_rows:
            meta = profiles.get(row["sedar_profile_id"], {})
            decorated.append({**row, "name": meta.get("name")})
        email_sent = await notifications.send_new_filings_email(decorated)

    return RefreshSummary(
        companies_checked=len(profiles),
        new_filings=len(new_rows),
        email_sent=email_sent,
    )
