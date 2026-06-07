"""Filings scraper — TMX Money + SEDAR+, both via Playwright.

Designed to run on a self-hosted GitHub Actions runner (your home Mac).
Real consumer ISPs pass through Imperva; cloud datacenter IPs don't.

Per company on each run:
  1. SEDAR+ profile page — only if a profile URL is already cached on the
     watchlist row. Set the URL via the web UI (paste from your browser).
     Discovery via the SEDAR+ search box is disabled: SEDAR blocks the
     landing page when accessed programmatically.
  2. TMX Money news page (free, fast, no anti-bot).
  3. POST results to /api/filings/ingest — backend dedupes, inserts,
     emails via Resend.

Rendered HTML for every page is saved as a workflow artifact so any
parser tweak is a one-file change.
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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
BETWEEN_COMPANIES_MS = 2_500
ARTIFACT_DIR = Path("artifacts")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-CA', 'en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(i => ({ name: 'Plugin ' + i }))
});
window.chrome = window.chrome || { runtime: {} };
const origQuery = navigator.permissions && navigator.permissions.query;
if (origQuery) {
    navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(params);
}
"""


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


async def run_sedar(page: Page, target: dict) -> list[dict]:
    """Fetch filings from a cached SEDAR+ profile URL.

    Returns an empty list (and logs a warning) if no URL is cached.
    Users set the URL via the web UI by pasting it from their browser.
    """
    name = target.get("name") or target.get("ticker") or "?"
    ticker = target.get("ticker")
    profile_url = target.get("sedar_profile_url")

    if not profile_url:
        LOG.info("SEDAR+: skipping %r — no profile URL set (add via web UI)", name)
        return []

    rows, profile_html = await sedar_plus.fetch_filings(page, profile_url)
    _save_html(f"sedar_profile_{_slug(name)}", profile_html)
    for r in rows:
        r["ticker"] = ticker
        r["sedar_profile_id"] = target.get("sedar_profile_id")
    return rows


# ---------- main ----------

async def run(playwright: Playwright) -> int:
    ARTIFACT_DIR.mkdir(exist_ok=True)
    async with httpx.AsyncClient() as client:
        targets = await fetch_targets(client)

    LOG.info("Got %d scrape target(s)", len(targets))
    if not targets:
        return 0

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    headless = os.environ.get("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
    try:
        browser = await playwright.chromium.launch(
            channel="chrome", headless=headless, args=launch_args
        )
        LOG.info("Launched real Chrome (channel=chrome, headless=%s)", headless)
    except Exception as exc:
        LOG.warning("Real Chrome unavailable (%s); falling back to bundled Chromium", exc)
        browser = await playwright.chromium.launch(headless=headless, args=launch_args)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 900},
        locale="en-CA",
        timezone_id="America/Toronto",
        extra_http_headers={"Accept-Language": "en-CA,en;q=0.9"},
    )
    await context.add_init_script(STEALTH_JS)
    page = await context.new_page()

    all_filings: list[dict] = []

    try:
        for i, target in enumerate(targets):
            if i:
                await page.wait_for_timeout(BETWEEN_COMPANIES_MS)
            name = target.get("name") or target.get("ticker") or "?"
            LOG.info("---- %s ----", name)
            # SEDAR first: navigate to the profile page directly (no search UI).
            # This avoids the landing-page block that SEDAR+ applies to
            # automated sessions that arrive from a different domain.
            try:
                sedar_rows = await run_sedar(page, target)
                all_filings.extend(sedar_rows)
            except Exception:
                LOG.exception("SEDAR scrape failed for %s", name)
            # TMX second.
            try:
                tmx_rows = await run_tmx(page, target)
                all_filings.extend(tmx_rows)
            except Exception:
                LOG.exception("TMX scrape failed for %s", name)
    finally:
        await context.close()
        await browser.close()

    LOG.info(
        "Collected %d filings (%d TMX, %d SEDAR)",
        len(all_filings),
        sum(1 for f in all_filings if f.get("source") == "tmx_money"),
        sum(1 for f in all_filings if f.get("source") == "sedar_plus"),
    )

    if not all_filings:
        return 0

    async with httpx.AsyncClient() as client:
        summary = await post_ingest(client, all_filings, [])
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
