from fastapi import APIRouter, Query

from ..services import yahoo

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=10, ge=1, le=25),
) -> list[dict]:
    """Search Canadian listings on Yahoo Finance — used by the add-company UI."""
    return await yahoo.search(q, limit=limit)
