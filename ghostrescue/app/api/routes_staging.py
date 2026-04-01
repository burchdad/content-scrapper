"""Staging API — the controlled handoff point between GhostScraper and GhostRescue.

Endpoints
---------
POST   /api/v1/staging/submit            -- GhostScraper submits a discovered signal
GET    /api/v1/staging/queue             -- Analyst views pending queue
POST   /api/v1/staging/{id}/approve      -- Analyst approves → queued for ingest
POST   /api/v1/staging/{id}/reject       -- Analyst rejects with reason
GET    /api/v1/staging/sources           -- View the approved source registry

Design rule enforced here
--------------------------
No staging item influences GhostRescue scoring until an analyst (or auto-validator)
has set its status to 'approved'.  The /staging/submit endpoint is the ONLY path
for external / scraper data to enter the system.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.source_registry import list_approved_sources
from app.services.staging_service import StagingService

router = APIRouter(prefix="/api/v1/staging", tags=["staging"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class StagingSubmitRequest(BaseModel):
    source_name: str = Field(min_length=2, max_length=256)
    source_url: str | None = Field(default=None, max_length=2048)
    submitted_by: str = Field(default="ghostscraper", max_length=128)
    payload: dict = Field(
        description="Raw scraper payload. Must include at least one of: canonical_name, name, title."
    )


class StagingApproveRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=128)
    notes: str | None = None


class StagingRejectRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2048)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/submit")
async def staging_submit(
    request: StagingSubmitRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Submit a signal from GhostScraper (or any external source) for review.

    The payload is validated and normalised.  If the source is already in the
    approved registry, it is auto-approved.  Otherwise it enters the 'pending'
    queue for analyst review.

    **This is the only permitted entry point for unvalidated data.**
    """
    svc = StagingService(db)
    result = await svc.submit(
        source_name=request.source_name,
        source_url=request.source_url,
        raw_payload=request.payload,
        submitted_by=request.submitted_by,
    )
    if result.get("status") == "rejected":
        # Validation failure — 422 with detail
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Payload failed validation and was not staged.",
                "errors": result.get("errors", []),
                "warnings": result.get("warnings", []),
            },
        )
    return result


@router.get("/queue")
async def staging_queue(
    status: str = "pending",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the staging queue filtered by status (pending | approved | rejected).

    Use this endpoint to review what GhostScraper has discovered before
    allowing it to influence intelligence scoring.
    """
    if status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be pending | approved | rejected")
    svc = StagingService(db)
    return await svc.list_queue(status=status, limit=min(limit, 200), offset=offset)


@router.post("/{staged_id}/approve")
async def staging_approve(
    staged_id: str,
    request: StagingApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Approve a staged signal.

    Approved signals are picked up by the next ingest cycle and included in
    GhostRescue scoring at their trust_level-capped influence weight.
    """
    svc = StagingService(db)
    try:
        return await svc.approve(
            staged_id=staged_id,
            reviewed_by=request.reviewed_by,
            notes=request.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{staged_id}/reject")
async def staging_reject(
    staged_id: str,
    request: StagingRejectRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Reject a staged signal with a required reason.

    Rejected signals are retained for audit purposes but excluded from scoring.
    """
    svc = StagingService(db)
    try:
        return await svc.reject(
            staged_id=staged_id,
            reviewed_by=request.reviewed_by,
            reason=request.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sources")
async def staging_sources() -> dict:
    """
    Return the full source registry — which sources are approved, their trust
    levels, influence caps, and whether they require staging.

    Use this to understand what GhostScraper outputs need staging vs. which
    sources can bypass the queue.
    """
    sources = list_approved_sources()
    by_trust: dict[str, list] = {}
    for s in sources:
        by_trust.setdefault(s["trust_level"], []).append(s)

    return {
        "total_sources": len(sources),
        "by_trust_level": by_trust,
        "trust_level_influence_caps": {
            "law_enforcement_direct": 1.0,
            "validated_public": 0.85,
            "validated_osint": 0.60,
            "unvalidated_osint": 0.20,
            "staged_pending": 0.0,
        },
        "architecture_note": (
            "GhostScraper submits to /api/v1/staging/submit. "
            "Only approved, trusted sources write directly to /api/v1/ingest/*. "
            "Staging is the controlled handoff between exploration and intelligence."
        ),
    }
