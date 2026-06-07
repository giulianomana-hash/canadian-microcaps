"""Scrape SEDAR+ filings for every watched company and ingest them.

Runs inside GitHub Actions. A real Chromium via Playwright clears
Imperva's bot challenge that blocks Render's backend.

Per company on each run:
  1. If we don't already have the SEDAR+ profile URL cached, search SEDAR+
     by company name and pick the most relevant result.
  2. Open the profile page and parse the filings out of the DOM.
  3. POST all results (filings + newly-discovered URLs) to
     /api/filings/ingest. The backend dedupes, inserts, emails.

Every rendered page is uploaded as a workflow artifact so the parser /
selectors can be fixed without trial-and-error redeploys.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import (
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

LOG = logging.getLogger("scrape_sedar")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BACKEND_URL = os.environ["BACKEND_URL"].rstrip("/")
REFRESH_SECRET = os.environ["REFRESH_SECRET"]

SEDAR_BASE = "https://www.sedarplus.ca"
SEDAR_SEARCH_URL = SEDAR_BASE + "/csa-party/search/?searchText={q}"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
NAV_TIMEOUT_MS = 60_000
BETWEEN_COMPANIES_MS = 2_500
IMPERVA_SETTLE_MS = 3_000
ARTIFACT_DIR = Path("artifacts")


# ---------- backend I/O ----------

async def fetch_targets(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(
        f"{BACKEND_URL}/api/scrape-targets",
        headers={"Authorization": f"Bearer {REFRESH_SECRET}"},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


async def post_ingest(
    client: httpx.AsyncClient, filings: list[dict], discovered_urls: list[dict]
) -> dict:
    payload = {"filings": filings, "discovered_urls": discovered_urls}
    resp = await client.post(
        f"{BACKEND_URL}/api/filings/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {REFRESH_SECRET}"},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------- parsing helpers ----------

DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d")
_FILING_ID_RE = re.compile(r"(?:id|filingId|submissionId)=([\w-]+)", re.IGNORECASE)
_PROFILE_HREF_RE = re.compile(r"/csa-party/records/[\w./?=&-]+", re.IGNORECASE)


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


# ---------- SEDAR+ search → profile URL ----------

async def discover_profile_url(page: Page, name: str) -> Optional[str]:
    """Open SEDAR+ search for `name`, return the best matching profile URL."""
    search_url = SEDAR_SEARCH_URL.format(q=quote_plus(name))
    try:
        await page.goto(search_url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("Timeout on SEDAR+ search for %r", name)
        return None
    await page.wait_for_timeout(IMPERVA_SETTLE_MS)
    html = await page.content()

    # Save the search HTML for diagnosis.
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())[:40]
    (ARTIFACT_DIR / f"search_{slug}.html").write_text(html or "", encoding="utf-8")

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
        LOG.warning("No SEDAR+ profile links found for %r", name)
        return None
    score, label, href = best
    if score < 0.35:
        LOG.warning("Best SEDAR+ match for %r is %r (score %.2f); skipping", name, label, score)
        return None
    url = href if href.startswith("http") else urljoin(SEDAR_BASE, href)
    LOG.info("Discovered SEDAR+ URL for %r → %s (%s, %.2f)", name, label, url, score)
    return url


# ---------- filings parsing ----------

def parse_filings(html: str, base_url: str) -> list[dict]:
    """Best-effort parse of a rendered company profile page.

    Looks for table rows that contain a date and a link. SEDAR+ does not
    publish a stable DOM; this is intentionally tolerant.
    """
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
                url = urljoin(base_url, url)
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
    return hits


# ---------- per-company driver ----------

async def scrape_company(page: Page, target: dict) -> tuple[list[dict], Optional[str]]:
    """Returns (filings, newly_discovered_url_or_None)."""
    name = target.get("name") or ""
    url = target.get("sedar_profile_url")
    discovered_url: Optional[str] = None

    if not url:
        LOG.info("No cached SEDAR+ URL for %r — discovering via search", name)
        url = await discover_profile_url(page, name)
        discovered_url = url

    if not url:
        return [], None

    LOG.info("Visiting %s — %s", name, url)
    try:
        await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("Timeout loading %s; using whatever DOM is ready.", url)
    await page.wait_for_timeout(IMPERVA_SETTLE_MS)
    html = await page.content()

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())[:40]
    (ARTIFACT_DIR / f"profile_{slug}.html").write_text(html or "", encoding="utf-8")

    rows = parse_filings(html, url)
    for r in rows:
        r["sedar_profile_id"] = target.get("sedar_profile_id")
        r["ticker"] = target.get("ticker")
    LOG.info("  parsed %d filings", len(rows))
    return rows, discovered_url


async def run(playwright: Playwright) -> int:
    ARTIFACT_DIR.mkdir(exist_ok=True)
    async with httpx.AsyncClient() as client:
        targets = await fetch_targets(client)

    LOG.info("Got %d scrape target(s) from backend", len(targets))
    if not targets:
        return 0

    browser = await playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 900},
        locale="en-CA",
        timezone_id="America/Toronto",
    )
    page = await context.new_page()

    all_filings: list[dict] = []
    discovered: list[dict] = []
    try:
        for i, target in enumerate(targets):
            if i:
                await page.wait_for_timeout(BETWEEN_COMPANIES_MS)
            try:
                rows, new_url = await scrape_company(page, target)
            except Exception:
                LOG.exception("Scrape failed for %s", target.get("name"))
                continue
            all_filings.extend(rows)
            if new_url:
                discovered.append({"watchlist_id": target["id"], "sedar_profile_url": new_url})
    finally:
        await context.close()
        await browser.close()

    LOG.info(
        "Collected %d filings, discovered %d new SEDAR URLs",
        len(all_filings),
        len(discovered),
    )
    if not all_filings and not discovered:
        return 0

    async with httpx.AsyncClient() as client:
        summary = await post_ingest(client, all_filings, discovered)
    LOG.info("Backend response: %s", summary)
    return summary.get("inserted", 0)


async def main() -> None:
    async with async_playwright() as p:
        inserted = await run(p)
    LOG.info("Done. %d new filing(s) inserted.", inserted)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        LOG.exception("Fatal scraper error")
        sys.exit(1)
