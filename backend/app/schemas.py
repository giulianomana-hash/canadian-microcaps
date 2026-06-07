from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class WatchlistEntryCreate(BaseModel):
    user_id: str = Field(..., description="Owning user id (free-form string for now).")
    sedar_profile_id: Optional[str] = Field(
        default=None,
        description="SEDAR+ profile / party id (if known).",
    )
    sedar_profile_url: Optional[str] = Field(
        default=None,
        description="Full SEDAR+ company profile URL the scraper should open.",
    )
    company_id: Optional[str] = None
    ticker: Optional[str] = None
    name: str
    sector: Optional[str] = None
    exchange: Optional[str] = None
    jurisdiction: Optional[str] = None
    market_cap: Optional[float] = None


class WatchlistEntry(WatchlistEntryCreate):
    id: str
    created_at: datetime


class CompanySearchResult(BaseModel):
    sedar_profile_id: str
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    jurisdiction: Optional[str] = None


class Filing(BaseModel):
    id: str
    company_id: Optional[str] = None
    sedar_profile_id: Optional[str] = None
    sedar_filing_id: Optional[str] = None
    ticker: Optional[str] = None
    filing_type: str
    filing_date: date
    url: str
    title: Optional[str] = None
    source: Optional[str] = "sedar_plus"
    created_at: datetime


class FilingIngest(BaseModel):
    sedar_profile_id: Optional[str] = None
    sedar_filing_id: str
    ticker: Optional[str] = None
    filing_type: str
    filing_date: date
    url: str
    title: Optional[str] = None
    source: str = "sedar_plus"


class DiscoveredSedarUrl(BaseModel):
    watchlist_id: str
    sedar_profile_url: str


class FilingsIngestPayload(BaseModel):
    filings: list[FilingIngest] = []
    discovered_urls: list[DiscoveredSedarUrl] = []


class IngestSummary(BaseModel):
    received: int
    inserted: int
    email_sent: bool


class RefreshSummary(BaseModel):
    companies_checked: int
    new_filings: int
    email_sent: bool
