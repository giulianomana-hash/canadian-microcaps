"""SEDAR+ scraper via ScrapingBee (residential proxies + JS rendering).

SEDAR+ is fronted by Imperva, which hard-blocks every automated browser we
can launch — direct profile URLs return a fake 404, and the landing page
trips the "does not comply with terms" block. ScrapingBee routes our
requests through residential IPs and runs the page in their own headless
Chrome, returning rendered HTML.

ScrapingBee credit cost (residential render):
  * Discovery search: ~25 credits/call, runs once per company (then cached)
  * Profile fetch: ~25 credits/call, runs every scrape
  * Free tier: 1,000 credits/month — enough for ~20 companies twice daily

Discovery only runs once per company. After the first successful run the
SEDAR+ profile URL is cached on the watchlist row, so subsequent runs only
fetch the profile page directly.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

LOG = logging.getLogger("sedar_plus")

SEDAR_BASE = "https://www.sedarplus.ca"
SCRAPINGBEE_ENDPOINT = "https://app.scrapingbee.com/api/v1/"

SCRAPINGBEE_TIMEOUT = 90.0

DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d")
_PROFILE_HREF_RE = re.compile(r"/csa-party/viewInstance/view\.html\?id=[\w-]+", re.IGNORECASE)
_FILING_ID_RE = re.compile(r"(?:id|filingId|submissionId)=([\w-]+)", re.IGNORECASE)


def _api_key() -> str:
    key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not key:
        raise RuntimeError("SCRAPINGBEE_API_KEY not set — cannot reach SEDAR+")
    return key


async def _fetch(url: str, *, wait_ms: int = 5_000) -> str:
    """Fetch a SEDAR+ URL through ScrapingBee. Returns rendered HTML.

    SEDAR+ is fronted by Radware Bot Manager (not Imperva as we first
    thought). ScrapingBee's `premium_proxy` pool gets captcha-walled by
    Radware, so we need `stealth_proxy=true` — their highest-tier pool
    designed for sites with aggressive bot detection. 75 credits/call vs
    25, so this only makes sense if it actually works. `stealth_proxy`
    is mutually exclusive with `premium_proxy` and `country_code`.
    """
    params = {
        "api_key": _api_key(),
        "url": url,
        "render_js": "true",
        "stealth_proxy": "true",
        "wait": str(wait_ms),
        "block_resources": "false",
    }
    async with httpx.AsyncClient(timeout=SCRAPINGBEE_TIMEOUT) as client:
        resp = await client.get(SCRAPINGBEE_ENDPOINT, params=params)
        if resp.status_code != 200:
            LOG.warning("ScrapingBee %s for %s: %s", resp.status_code, url, resp.text[:200])
            resp.raise_for_status()
        return resp.text


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


async def discover_profile_url(name: str) -> tuple[Optional[str], str]:
    """Returns (profile_url, raw_html). URL is None if no good match.

    Hits SEDAR+'s search URL directly via ScrapingBee — residential IP +
    headless Chrome means Imperva doesn't fingerprint us as automation.
    """
    search_url = (
        SEDAR_BASE
        + "/csa-party/search/profilesearch.html?"
        + urlencode({"q": name, "lang": "en"})
    )
    try:
        html = await _fetch(search_url, wait_ms=6_000)
    except Exception as exc:
        LOG.warning("SEDAR+ discovery fetch failed for %r: %s", name, exc)
        return None, ""

    if _looks_like_block_page(html):
        LOG.warning("SEDAR+ served the Imperva block page for search %r", name)
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


async def fetch_filings(profile_url: str) -> tuple[list[dict], str]:
    """Returns (filings, raw_html). Empty list on block page or no rows."""
    try:
        html = await _fetch(profile_url, wait_ms=5_000)
    except Exception as exc:
        LOG.warning("SEDAR+ profile fetch failed for %s: %s", profile_url, exc)
        return [], ""

    if _looks_like_block_page(html):
        LOG.warning("SEDAR+ served the Imperva block page for %s", profile_url)
        return [], html

    soup = BeautifulSoup(html, "html.parser")
    # Diagnostic fingerprint so we can see what ScrapingBee actually
    # returned without downloading the artifact every time.
    title = (soup.title.string.strip() if soup.title and soup.title.string else "<no title>")
    table_count = len(soup.find_all("table"))
    profile_links = len(_PROFILE_HREF_RE.findall(html))
    LOG.info(
        "SEDAR+ profile fingerprint: title=%r len=%d tables=%d profile_links=%d",
        title[:120], len(html), table_count, profile_links,
    )
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
