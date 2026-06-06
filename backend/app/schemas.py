from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class WatchlistEntryCreate(BaseModel):
    user_id: str = Field(..., description="Owning user id (free-form string for now).")
    company_id: Optional[str] = None
    ticker: str
    name: str
    sector: Optional[str] = None
    exchange: Optional[str] = None
    market_cap: Optional[float] = Field(
        default=None,
        description="Market capitalisation in CAD. Soft-capped at 50M on the client.",
    )


class WatchlistEntry(WatchlistEntryCreate):
    id: str
    created_at: datetime


class Filing(BaseModel):
    id: str
    company_id: Optional[str] = None
    ticker: str
    filing_type: str
    filing_date: date
    url: str
    created_at: datetime
