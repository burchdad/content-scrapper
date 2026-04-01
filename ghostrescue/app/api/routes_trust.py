from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.schemas import (
    FeedbackIn,
    FeedbackOut,
    FeedbackStats,
    TrustConfigOut,
    TrustConfigUpdateRequest,
)
from app.services.feedback_service import FeedbackService
from app.services.trust_service import TrustService

router = APIRouter(prefix="/api/v1", tags=["trust"])
settings = get_settings()


@router.get("/trust/config", response_model=TrustConfigOut)
async def get_trust_config(db: AsyncSession = Depends(get_db)) -> TrustConfigOut:
    config = await TrustService(db).get_or_create_config()
    return TrustConfigOut(
        risk_medium_threshold=config.risk_medium_threshold,
        risk_high_threshold=config.risk_high_threshold,
        risk_critical_threshold=config.risk_critical_threshold,
        cluster_similarity_threshold=config.cluster_similarity_threshold,
        false_positive_penalty=config.false_positive_penalty,
        updated_at=config.updated_at,
        disclaimer=settings.disclaimer,
    )


@router.patch("/trust/config", response_model=TrustConfigOut)
async def update_trust_config(
    request: TrustConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> TrustConfigOut:
    svc = TrustService(db)
    config = await svc.update_config(
        risk_medium_threshold=request.risk_medium_threshold,
        risk_high_threshold=request.risk_high_threshold,
        risk_critical_threshold=request.risk_critical_threshold,
        cluster_similarity_threshold=request.cluster_similarity_threshold,
        false_positive_penalty=request.false_positive_penalty,
    )
    return TrustConfigOut(
        risk_medium_threshold=config.risk_medium_threshold,
        risk_high_threshold=config.risk_high_threshold,
        risk_critical_threshold=config.risk_critical_threshold,
        cluster_similarity_threshold=config.cluster_similarity_threshold,
        false_positive_penalty=config.false_positive_penalty,
        updated_at=config.updated_at,
        disclaimer=settings.disclaimer,
    )


@router.post("/trust/feedback", response_model=FeedbackOut)
async def add_feedback(
    request: FeedbackIn,
    db: AsyncSession = Depends(get_db),
) -> FeedbackOut:
    row = await FeedbackService(db).add(request)
    return FeedbackOut.model_validate(row)


@router.get("/trust/feedback", response_model=list[FeedbackOut])
async def list_feedback(
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackOut]:
    rows = await FeedbackService(db).list(limit=limit)
    return [FeedbackOut.model_validate(r) for r in rows]


@router.get("/trust/stats", response_model=FeedbackStats)
async def trust_stats(db: AsyncSession = Depends(get_db)) -> FeedbackStats:
    trust = TrustService(db)
    feedback_rows = await FeedbackService(db).list(limit=10_000)
    return FeedbackStats(
        total_feedback=len(feedback_rows),
        false_positive_rate=await trust.false_positive_rate(),
        adaptive_penalty=await trust.adaptive_penalty(),
        disclaimer=settings.disclaimer,
    )
