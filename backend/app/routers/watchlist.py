from fastapi import APIRouter, HTTPException, status

from ..schemas import WatchlistEntry, WatchlistEntryCreate
from ..supabase_client import get_supabase

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

TABLE = "watchlist"


@router.get("", response_model=list[WatchlistEntry])
def list_watchlist() -> list[WatchlistEntry]:
    response = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return [WatchlistEntry(**row) for row in (response.data or [])]


@router.post("", response_model=WatchlistEntry, status_code=status.HTTP_201_CREATED)
def add_watchlist_entry(entry: WatchlistEntryCreate) -> WatchlistEntry:
    payload = entry.model_dump(exclude_none=True)
    response = get_supabase().table(TABLE).insert(payload).execute()
    rows = response.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase did not return the inserted row.",
        )
    return WatchlistEntry(**rows[0])


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(entry_id: str) -> None:
    response = get_supabase().table(TABLE).delete().eq("id", entry_id).execute()
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist entry {entry_id} not found.",
        )
