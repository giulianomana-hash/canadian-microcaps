"""Email notifications via Resend (https://resend.com).

Skipped silently when RESEND_API_KEY or NOTIFY_EMAIL is unset, so the rest
of the pipeline keeps working without email configured.
"""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


def _filings_html(rows: Iterable[dict]) -> str:
    items = "".join(
        f'<li><strong>{r.get("ticker") or r.get("name") or "—"}</strong> '
        f'— {r.get("filing_type")} ({r.get("filing_date")}) '
        f'<a href="{r.get("url")}">view</a></li>'
        for r in rows
    )
    return (
        "<p>New SEDAR+ filings detected on your watchlist:</p>"
        f"<ul>{items}</ul>"
        '<p style="color:#888;font-size:12px">— SedarWatchlist</p>'
    )


async def send_new_filings_email(rows: list[dict]) -> bool:
    """Send a summary email for newly seen filings. Returns True on success."""
    if not rows:
        return False

    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("Skipping email: RESEND_API_KEY not set (%d new filings).", len(rows))
        return False
    if not settings.notify_email:
        logger.info("Skipping email: NOTIFY_EMAIL not set (%d new filings).", len(rows))
        return False

    payload = {
        "from": settings.resend_from,
        "to": [settings.notify_email],
        "subject": f"SedarWatchlist — {len(rows)} new filing(s)",
        "html": _filings_html(rows),
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(RESEND_API, json=payload, headers=headers)
            resp.raise_for_status()
        logger.info("Sent filings email to %s (%d rows).", settings.notify_email, len(rows))
        return True
    except Exception as exc:
        logger.warning("Resend email failed: %s", exc)
        return False
