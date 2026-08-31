"""Dashboard statistics route."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StatsServiceDep
from app.schemas.stats import StatsResponse

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "",
    response_model=StatsResponse,
    summary="Aggregate repository and job counts for the dashboard",
)
async def get_stats(stats: StatsServiceDep) -> StatsResponse:
    return stats.get_stats()
