"""Cross-source intelligence linking routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.cross_source_linker import CrossSourceLinker

router = APIRouter(prefix="/api/v1/links", tags=["intelligence"])

_DISCLAIMER = (
    "Cross-source links are automated pattern matches only. "
    "They do not constitute verified identity or causal connections. "
    "Human analyst review is required before any investigative action."
)


@router.get("/cross-source")
async def find_cross_source_links(
    anchor: str | None = Query(
        default=None,
        description="Comma-separated source name patterns for anchor side (e.g. 'namus')",
    ),
    target: str | None = Query(
        default=None,
        description="Comma-separated source name patterns for target side (e.g. 'fbi most wanted')",
    ),
    days: int = Query(default=90, ge=1, le=365, description="Look-back window in days"),
    max_candidates: int = Query(default=50, ge=1, le=200),
    min_score: float = Query(default=0.25, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Find cross-source intelligence links between signals from different origins.

    Typical usage:
    - anchor=namus&target=fbi+most+wanted  → NamUs victims linked to FBI subjects
    - (no params)                           → all-source cross-tier comparison

    Matching strategies: geographic overlap, temporal proximity, name tokens,
    corroborating signal type.

    **All results are candidate links only — not confirmed identities.**
    """
    anchor_patterns = [p.strip() for p in anchor.split(",")] if anchor else None
    target_patterns = [p.strip() for p in target.split(",")] if target else None

    linker = CrossSourceLinker(
        db,
        time_window_days=days,
        min_link_score=min_score,
    )
    result = await linker.find_links(
        anchor_source_patterns=anchor_patterns,
        target_source_patterns=target_patterns,
        max_candidates=max_candidates,
    )
    return result


@router.get("/cross-source/summary")
async def cross_source_summary(
    days: int = Query(default=90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    High-level cross-source coverage stats.

    Returns signal counts by source tier and whether cross-source linking
    is feasible given current data in the time window.
    """
    linker = CrossSourceLinker(db, time_window_days=days)
    stats = await linker.summary_stats()
    stats["disclaimer"] = _DISCLAIMER
    return stats
