from fastapi import APIRouter, Query

from ..schemas import CompanySearchResult
from ..services import sedar_plus

router = APIRouter(prefix="/api/sedar", tags=["sedar"])


@router.get("/search", response_model=list[CompanySearchResult])
async def search(
    q: str = Query(..., min_length=2, description="Company name or ticker fragment."),
    limit: int = Query(default=15, ge=1, le=50),
) -> list[CompanySearchResult]:
    hits = await sedar_plus.search_companies(q, limit=limit)
    return [CompanySearchResult(**hit.to_dict()) for hit in hits]
