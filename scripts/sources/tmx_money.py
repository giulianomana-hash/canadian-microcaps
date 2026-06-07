"""TMX Money news scraper.

Public news page per ticker on TSX / TSXV. No anti-bot wall — TMX wants
Google to index these pages. We use Playwright (already in scope for the
runner) to render and parse.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

LOG = logging.getLogger("tmx_money")

# TMX Money uses the bare ticker for all Canadian listings — no exchange
# suffix in the URL. Strip Yahoo/Finnhub suffixes before building the URL.
KNOWN_SUFFIXES = (".TO", ".V", ".CN", ".NE")
NAV_TIMEOUT_MS = 45_000
SETTLE_MS = 2_500

DATE_PATTERNS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %b %Y")


def url_for(ticker: str) -> Optional[str]:
    if not ticker:
        return None
    base = ticker
    for suffix in KNOWN_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"https://money.tmx.com/en/quote/{base}/news"


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


def _parse_news(html: str) -> list[dict]:
    """Best-effort parse of TMX's news page.

    News items are rendered as a list of links + headlines + dates. The
    exact DOM differs between releases; we look for any anchor with a
    nearby date.
    """
    soup = BeautifulSoup(html, "html.parser")
    hits: list[dict] = []
    seen_urls: set[str] = set()

    candidates = soup.select(
        "article a, li a, div[class*='news'] a, div[class*='story'] a, "
        "section a[href]"
    )
    for link in candidates:
        href = link.get("href") or ""
        if not href or href.startswith("#"):
            continue
        url = href if href.startswith("http") else f"https://money.tmx.com{href}"
        if url in seen_urls:
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue
        date_value: Optional[date] = None
        for ancestor in (link, link.parent, link.parent.parent if link.parent else None):
            if not ancestor:
                continue
            txt = ancestor.get_text(" ", strip=True)
            m = re.search(r"(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2},\s*\d{4})", txt)
            if m:
                date_value = _parse_date(m.group(1))
                if date_value:
                    break
        if not date_value:
            continue
        seen_urls.add(url)
        hits.append(
            {
                "sedar_filing_id": url,
                "filing_type": "Press Release",
                "filing_date": date_value.isoformat(),
                "url": url,
                "title": title,
                "source": "tmx_money",
            }
        )
    return hits


async def scrape(page: Page, ticker: str) -> tuple[list[dict], str]:
    """Returns (filings, rendered_html). Empty list if ticker isn't on TMX."""
    url = url_for(ticker)
    if not url:
        return [], ""
    LOG.info("TMX Money: visiting %s", url)
    try:
        await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("TMX Money timeout for %s", url)
    await page.wait_for_timeout(SETTLE_MS)
    html = await page.content()
    rows = _parse_news(html)
    LOG.info("TMX Money: parsed %d items for %s", len(rows), ticker)
    return rows, html
