from fastapi import APIRouter, Query

from ..schemas import Filing
from ..supabase_client import get_supabase

router = APIRouter(prefix="/api/filings", tags=["filings"])

TABLE = "filings"


@router.get("", response_model=list[Filing])
def list_filings(
    limit: int = Query(default=100, ge=1, le=500),
    ticker: str | None = Query(default=None, description="Optional ticker filter."),
) -> list[Filing]:
    query = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .order("filing_date", desc=True)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if ticker:
        query = query.eq("ticker", ticker.upper())
    response = query.execute()
    return [Filing(**row) for row in (response.data or [])]
