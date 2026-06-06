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


@router.get("/diagnose")
async def diagnose(q: str = Query(default="shopify")) -> dict:
    """Probe several candidate SEDAR+ endpoints and report what each returns.

    Public route, intentionally no auth — only returns external HTTP metadata
    plus a short preview of the body so we can identify the right endpoint.
    """
    return await sedar_plus.diagnose(q)
