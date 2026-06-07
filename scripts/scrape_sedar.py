"""Scrape SEDAR+ filings for every watched company and ingest them.

This script runs inside the GitHub Actions runner (Ubuntu + Chromium +
Playwright). GitHub's IPs rotate per job and a real browser handles
Imperva's bot challenge, so we bypass the wall that blocks Render's
backend.

Flow:
  1. GET /api/scrape-targets to learn which companies + URLs to visit
  2. For each, open the SEDAR+ profile page in headless Chromium and parse
     the filings list/table out of the rendered DOM
  3. POST the collected filings to /api/filings/ingest (auth'd) — the
     backend dedupes, inserts new rows, and sends an email summary
  4. Always save the rendered HTML of each company page as a workflow
     artifact, so we can fix the parser without re-deploying when SEDAR+
     restructures their DOM
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

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

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
NAV_TIMEOUT_MS = 60_000
BETWEEN_COMPANIES_MS = 2_500
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


async def post_ingest(client: httpx.AsyncClient, filings: list[dict]) -> dict:
    resp = await client.post(
        f"{BACKEND_URL}/api/filings/ingest",
        json={"filings": filings},
        headers={"Authorization": f"Bearer {REFRESH_SECRET}"},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------- parsing ----------

DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d")


def _parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Fallback: ISO-like prefix
    if len(text) >= 10:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def parse_filings(html: str, base_url: str) -> list[dict]:
    """Best-effort parse of a rendered SEDAR+ company profile page.

    SEDAR+ does not have a stable public DOM. This routine looks for any
    table or list whose headers/labels look filing-shaped (date + type + a
    link). It tolerates missing optional fields.
    """
    soup = BeautifulSoup(html, "html.parser")
    hits: list[dict] = []
    seen_keys: set[str] = set()

    # Strategy 1 — table rows that include a date cell and a link.
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
                if txt and not _parse_date(txt) and txt.lower() not in {"view", "open", "pdf"}:
                    filing_type = txt
                    break
            url = link["href"]
            if url.startswith("/"):
                url = "https://www.sedarplus.ca" + url
            elif not url.startswith("http"):
                url = base_url.rsplit("/", 1)[0] + "/" + url
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


_FILING_ID_RE = re.compile(r"(?:id|filingId|submissionId)=([\w-]+)", re.IGNORECASE)


def _filing_id_from_url(url: str) -> Optional[str]:
    m = _FILING_ID_RE.search(url)
    if m:
        return m.group(1)
    # fallback: last numeric segment
    nums = re.findall(r"\d{4,}", url)
    return nums[-1] if nums else None


# ---------- scraping ----------

async def scrape_company(page: Page, target: dict) -> tuple[list[dict], str]:
    url = target.get("sedar_profile_url")
    if not url:
        LOG.warning("Skipping %s — no sedar_profile_url", target.get("name"))
        return [], ""
    LOG.info("Visiting %s — %s", target.get("name"), url)
    try:
        await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        LOG.warning("Timeout loading %s; using whatever DOM is ready.", url)
    # Let Imperva's JS challenge resolve.
    await page.wait_for_timeout(2_500)
    html = await page.content()
    rows = parse_filings(html, url)
    # Decorate with company metadata.
    for r in rows:
        r["sedar_profile_id"] = target.get("sedar_profile_id")
        r["ticker"] = target.get("ticker")
    LOG.info("  parsed %d filings", len(rows))
    return rows, html


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
    try:
        for i, target in enumerate(targets):
            if i:
                await page.wait_for_timeout(BETWEEN_COMPANIES_MS)
            rows, html = await scrape_company(page, target)
            slug = re.sub(r"[^a-z0-9]+", "_", (target.get("name") or "company").lower())[:40]
            (ARTIFACT_DIR / f"{slug}.html").write_text(html or "", encoding="utf-8")
            all_filings.extend(rows)
    finally:
        await context.close()
        await browser.close()

    LOG.info("Collected %d filing rows from %d companies", len(all_filings), len(targets))
    if not all_filings:
        return 0

    async with httpx.AsyncClient() as client:
        summary = await post_ingest(client, all_filings)
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
