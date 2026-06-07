"""Filings scraper — orchestrates TMX Money (free) and SEDAR+ via
ScraperAPI (paid quota) per watched company.

Runs inside GitHub Actions:
  1. Fetch scrape targets from backend.
  2. For each company:
     - If the ticker is TSX/TSXV/NEO → scrape TMX Money (free, every run).
     - Always attempt SEDAR+ via ScraperAPI when SCRAPERAPI_KEY is set
       (covers CSE-only listings and SEDAR-only regulatory filings).
  3. POST the combined results to /api/filings/ingest. Backend dedupes,
     inserts, and emails.

Rendered HTML for every page is uploaded as an Actions artifact so any
parser fix is a one-file change.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

import httpx
from playwright.async_api import Page, Playwright, async_playwright

from sources import sedar_plus, tmx_money

LOG = logging.getLogger("scrape_filings")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BACKEND_URL = os.environ["BACKEND_URL"].rstrip("/")
REFRESH_SECRET = os.environ["REFRESH_SECRET"]
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "").strip()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
BETWEEN_COMPANIES_MS = 2_000
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


# ---------- helpers ----------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower())[:40]


def _save_html(name: str, html: str) -> None:
    if not html:
        return
    (ARTIFACT_DIR / f"{name}.html").write_text(html, encoding="utf-8")


# ---------- per-source drivers ----------

async def run_tmx(page: Page, target: dict) -> list[dict]:
    ticker = (target.get("ticker") or "").strip()
    if not ticker:
        return []
    rows, html = await tmx_money.scrape(page, ticker)
    _save_html(f"tmx_{_slug(ticker)}", html)
    for r in rows:
        r["ticker"] = ticker
        r["sedar_profile_id"] = target.get("sedar_profile_id")
    return rows


async def run_sedar(target: dict) -> tuple[list[dict], dict | None]:
    """Returns (filings, discovered_url_record_or_None)."""
    if not SCRAPERAPI_KEY:
        return [], None
    name = target.get("name") or ""
    ticker = target.get("ticker")
    profile_url = target.get("sedar_profile_url")
    discovered: dict | None = None

    if not profile_url:
        LOG.info("SEDAR+: no cached URL for %r — discovering", name)
        profile_url, search_html = await sedar_plus.discover_profile_url(SCRAPERAPI_KEY, name)
        _save_html(f"sedar_search_{_slug(name)}", search_html)
        if profile_url:
            discovered = {"watchlist_id": target["id"], "sedar_profile_url": profile_url}

    if not profile_url:
        return [], None

    rows, profile_html = await sedar_plus.fetch_filings(SCRAPERAPI_KEY, profile_url)
    _save_html(f"sedar_profile_{_slug(name)}", profile_html)
    for r in rows:
        r["ticker"] = ticker
        r["sedar_profile_id"] = target.get("sedar_profile_id")
    return rows, discovered


# ---------- main ----------

async def run(playwright: Playwright) -> int:
    ARTIFACT_DIR.mkdir(exist_ok=True)
    async with httpx.AsyncClient() as client:
        targets = await fetch_targets(client)

    LOG.info("Got %d scrape target(s)", len(targets))
    if SCRAPERAPI_KEY:
        LOG.info("SCRAPERAPI_KEY set — SEDAR+ layer is active.")
    else:
        LOG.warning("SCRAPERAPI_KEY not set — SEDAR+ layer disabled, TMX only.")

    if not targets:
        return 0

    browser = await playwright.chromium.launch(
        headless=True, args=["--disable-blink-features=AutomationControlled"]
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
            name = target.get("name") or target.get("ticker") or "?"
            LOG.info("---- %s ----", name)
            try:
                tmx_rows = await run_tmx(page, target)
                all_filings.extend(tmx_rows)
            except Exception:
                LOG.exception("TMX scrape failed for %s", name)
            try:
                sedar_rows, disc = await run_sedar(target)
                all_filings.extend(sedar_rows)
                if disc:
                    discovered.append(disc)
            except Exception:
                LOG.exception("SEDAR scrape failed for %s", name)
    finally:
        await context.close()
        await browser.close()

    LOG.info(
        "Collected %d filings (%d TMX, %d SEDAR), discovered %d SEDAR URLs",
        len(all_filings),
        sum(1 for f in all_filings if f.get("source") == "tmx_money"),
        sum(1 for f in all_filings if f.get("source") == "sedar_plus"),
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
