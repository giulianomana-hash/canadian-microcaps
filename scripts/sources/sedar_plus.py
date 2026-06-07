"""SEDAR+ scraper using Playwright directly.

Designed for a self-hosted runner with a residential home IP. Imperva
allows real consumer ISPs through; what it blocks is datacenter IPs
(Render, GitHub Actions cloud) and shared proxy pools.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

LOG = logging.getLogger("sedar_plus")

SEDAR_BASE = "https://www.sedarplus.ca"
SEDAR_LANDING_URL = SEDAR_BASE + "/landingpage/"

NAV_TIMEOUT_MS = 60_000
SETTLE_MS = 4_000   # let Imperva's JS challenge complete

# Candidate selectors for the SEDAR+ search box on the landing page.
# SEDAR+ is an SPA; deep-linking the search URL trips Imperva's
# "activity does not comply" block, so we type into the real box instead.
SEARCH_INPUT_SELECTORS = (
    "input[type='search']",
    "input[placeholder*='earch']",
    "input[name*='earch']",
    "input[aria-label*='earch']",
    "input[id*='earch']",
    "#searchText",
    "input.search-input",
)

DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d")
_PROFILE_HREF_RE = re.compile(r"/csa-party/viewInstance/view\.html\?id=[\w-]+", re.IGNORECASE)
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


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _looks_like_block_page(html: str) -> bool:
    head = (html or "")[:2000].lower()
    return "stormcaster" in head or "blocked by the system" in head or "support id" in head


async def _type_into_search(page: Page, name: str) -> bool:
    """Find the SPA search box, type the company name, submit. Returns
    True if we found a box to type into."""
    for selector in SEARCH_INPUT_SELECTORS:
        try:
            box = page.locator(selector).first
            if await box.count() == 0:
                continue
            await box.click(timeout=5_000)
            await box.fill("")
            await box.type(name, delay=60)
            await page.wait_for_timeout(500)
            await box.press("Enter")
            LOG.info("SEDAR+: typed %r into %s", name, selector)
            return True
        except Exception:
            continue
    return False


async def discover_profile_url(page: Page, name: str, screenshot_path=None) -> tuple[Optional[str], str]:
    """Returns (profile_url, raw_html). URL is None if no good match.

    Drives the SEDAR+ landing-page search box like a human rather than
    deep-linking the search URL (which Imperva blocks as non-compliant
    activity).
    """
    try:
        await page.goto(SEDAR_LANDING_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("SEDAR+ landing timeout for %r", name)
    await page.wait_for_timeout(SETTLE_MS)

    if _looks_like_block_page(await page.content()):
        LOG.warning("SEDAR+ blocked us on the landing page for %r", name)
        if screenshot_path:
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
            except Exception:
                pass
        return None, await page.content()

    typed = await _type_into_search(page, name)
    if not typed:
        LOG.warning("SEDAR+: could not locate a search box for %r", name)
    else:
        # Wait for SPA results to render.
        await page.wait_for_timeout(SETTLE_MS)

    if screenshot_path:
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception as exc:
            LOG.warning("Screenshot failed: %s", exc)

    html = await page.content()

    if _looks_like_block_page(html):
        LOG.warning("SEDAR+ served the Imperva block page for %r", name)
        return None, html

    soup = BeautifulSoup(html, "html.parser")
    best: tuple[float, str, str] | None = None
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not _PROFILE_HREF_RE.search(href):
            continue
        text = link.get_text(" ", strip=True)
        if not text:
            continue
        score = _similarity(text, name)
        if best is None or score > best[0]:
            best = (score, text, href)
    if not best:
        LOG.warning("SEDAR+: no profile links found for %r", name)
        return None, html
    score, label, href = best
    if score < 0.35:
        LOG.warning("SEDAR+: weak best match for %r — %r (%.2f); skipping", name, label, score)
        return None, html
    url = href if href.startswith("http") else urljoin(SEDAR_BASE, href)
    LOG.info("SEDAR+: discovered %r → %s (%.2f)", name, label, score)
    return url, html


async def fetch_filings(page: Page, profile_url: str) -> tuple[list[dict], str]:
    """Returns (filings, raw_html). Empty list on block page or no rows."""
    try:
        await page.goto(profile_url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("SEDAR+ profile timeout for %s", profile_url)
    await page.wait_for_timeout(SETTLE_MS)
    html = await page.content()

    if _looks_like_block_page(html):
        LOG.warning("SEDAR+ served the Imperva block page for %s", profile_url)
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
    return hits, html
