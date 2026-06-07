"""SEDAR+ scraper using Playwright directly.

Designed for a self-hosted runner with a residential home IP.

Discovery (searching the landing page) is disabled — SEDAR+ blocks
automated navigation to the search UI. Instead, users paste their
company's profile URL via the web UI and we go straight to that page.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

LOG = logging.getLogger("sedar_plus")

SEDAR_BASE = "https://www.sedarplus.ca"

NAV_TIMEOUT_MS = 60_000
SETTLE_MS = 5_000   # let the SPA render after navigation

DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d")
_FILING_ID_RE = re.compile(r"(?:id|filingId|submissionId)=([\w-]+)", re.IGNORECASE)


def _parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if len(text) >= 10:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _filing_id_from_url(url: str) -> Optional[str]:
    m = _FILING_ID_RE.search(url)
    if m:
        return m.group(1)
    nums = re.findall(r"\d{4,}", url)
    return nums[-1] if nums else None


def _looks_like_block_page(html: str) -> bool:
    """Detect SEDAR+ application-layer block page.

    The block page contains both 'blocked by the system' and 'support id'.
    Checking for both together avoids false positives from 'support id'
    appearing in SEDAR's own legitimate footer/help links.
    """
    head = (html or "")[:3000].lower()
    return (
        "stormcaster" in head
        or ("blocked by the system" in head and "support id" in head)
        or ("access denied" in head and "support id" in head)
        or ("does not appear to comply" in head)
    )


async def fetch_filings(page: Page, profile_url: str) -> tuple[list[dict], str]:
    """Navigate directly to a known SEDAR+ profile URL and parse filings.

    Returns (filings, raw_html). Empty list on block page or no rows.
    """
    LOG.info("SEDAR+: visiting profile %s", profile_url)
    try:
        await page.goto(profile_url, wait_until="load", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("SEDAR+ profile timeout for %s", profile_url)
    await page.wait_for_timeout(SETTLE_MS)
    html = await page.content()

    if _looks_like_block_page(html):
        LOG.warning("SEDAR+ blocked profile page for %s", profile_url)
        return [], html

    soup = BeautifulSoup(html, "html.parser")
    hits: list[dict] = []
    seen_keys: set[str] = set()

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            link = row.find("a", href=True)
            if not link:
                continue
            date_value = None
            for cell in cells:
                date_value = _parse_date(cell.get_text(" ", strip=True))
                if date_value:
                    break
            if not date_value:
                continue
            filing_type = ""
            for cell in cells:
                txt = cell.get_text(" ", strip=True)
                if txt and not _parse_date(txt) and txt.lower() not in {"view", "open", "pdf", "html"}:
                    filing_type = txt
                    break
            url = link["href"]
            if url.startswith("/"):
                url = SEDAR_BASE + url
            elif not url.startswith("http"):
                url = urljoin(profile_url, url)
            filing_id = _filing_id_from_url(url) or f"{date_value.isoformat()}|{filing_type}|{url}"
            if filing_id in seen_keys:
                continue
            seen_keys.add(filing_id)
            hits.append(
                {
                    "sedar_filing_id": filing_id,
                    "filing_type": filing_type or "Filing",
                    "filing_date": date_value.isoformat(),
                    "url": url,
                    "title": link.get_text(" ", strip=True) or None,
                    "source": "sedar_plus",
                }
            )

    LOG.info("SEDAR+: parsed %d filing(s) from %s", len(hits), profile_url)
    return hits, html
