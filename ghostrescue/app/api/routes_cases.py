from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.case import Case
from app.models.schemas import (
    AnalystDecisionIn,
    AnalystDecisionOut,
    CaseClusterOut,
    CaseClusterResponse,
    CaseEvaluateRequest,
    CaseListResponse,
    CaseOut,
    CaseSummaryOut,
)
from app.services.alert_intelligence_service import AlertIntelligenceService
from app.services.analyst_summary_service import AnalystSummaryService
from app.services.case_authority_normalization_service import CaseAuthorityNormalizationService
from app.services.case_priority_service import CasePriorityService
from app.services.correlation_service import CorrelationService
from app.services.entity_memory_service import EntityMemoryService
from app.services.feedback_service import (
    FeedbackService,
    decision_weight_for_notes,
    parse_decision_role,
    parse_decision_type,
)
from app.services.feedback_service import DecisionCapError
from app.services.case_cluster_service import CaseClusterService
from app.services.nlp.classifier import NLPClassifier
from app.services.scoring.risk_scorer import RiskScorer
from app.services.trust_service import TrustService

router = APIRouter(prefix="/api/v1", tags=["cases"])
settings = get_settings()

_classifier = NLPClassifier()
_scorer = RiskScorer()


def _case_out_with_priority(case: Case, priority: dict | None) -> CaseOut:
    out = CaseOut.model_validate(case)
    if priority:
        out.priority_score = float(priority.get("priority_score") or 0.0)
        out.priority_band = priority.get("priority_band")
        out.priority_explanation = priority.get("priority_explanation")
        out.corroboration_tier = priority.get("corroboration_tier")
        out.independent_corroboration = priority.get("independent_corroboration") or {}
    return out


@router.post("/cases/evaluate", response_model=CaseOut)
async def evaluate_case(
    request: CaseEvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    signals = _classifier.classify(request.text)
    correlation = await CorrelationService(db).entity_correlation_features(request.entity_id)
    penalty = await TrustService(db).adaptive_penalty()
    score = _scorer.score(
        signals=signals,
        entity_match_confidence=max(0.0, min(1.0, 0.5 + correlation.get("cross_source_reinforcement", 0.0) / 2)),
        signal_frequency_bonus=float(correlation.get("temporal_burst_24h", 0)),
        calibration_penalty=penalty,
        source_names=[request.source_name] * len(signals) if request.source_name else None,
    )

    case, alert = await AlertIntelligenceService(db).evaluate_and_create_case(
        entity_id=request.entity_id,
        risk_score=score.risk_score,
        confidence_score=score.confidence_score,
        system_confidence=score.system_confidence,
        explanation=score.explanation,
        signals=signals,
        correlation=correlation,
        score_calibration=score.calibration,
    )

    await EntityMemoryService(db).record_event(
        entity_id=request.entity_id,
        event_type="case_evaluated",
        summary=(
            f"Case {case.case_id} evaluated with risk={score.risk_score:.1f}, "
            f"signals={len(signals)}, alert={'yes' if alert else 'no'}."
        ),
        source_name=request.source_name,
        source_url=request.source_url,
        metadata={
            "case_id": case.case_id,
            "alert_id": alert.alert_id if alert else None,
            "risk_score": score.risk_score,
        },
    )

    return CaseOut.model_validate(case)


@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
    sort_by_priority: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> CaseListResponse:
    fetch_limit = min(40, max(limit * 2, 20)) if sort_by_priority else limit
    stmt = select(Case).order_by(Case.updated_at.desc()).limit(fetch_limit)
    count_stmt = select(func.count()).select_from(Case)
    if status:
        stmt = stmt.where(Case.status == status)
        count_stmt = count_stmt.where(Case.status == status)

    rows = await db.execute(stmt)
    total_row = await db.execute(count_stmt)
    cases = rows.scalars().all()

    priorities: dict[str, dict] = {}
    if sort_by_priority:
        priorities = await CasePriorityService(db).score_cases(cases, apply_saturation=True)
        cases = sorted(cases, key=lambda c: priorities.get(c.case_id, {}).get("priority_score", c.risk_score), reverse=True)
    cases = cases[:limit]

    return CaseListResponse(
        cases=[_case_out_with_priority(c, priorities.get(c.case_id)) for c in cases],
        total=total_row.scalar_one(),
        disclaimer=settings.disclaimer,
    )


@router.get("/cases/clusters", response_model=CaseClusterResponse)
async def get_case_clusters(db: AsyncSession = Depends(get_db)) -> CaseClusterResponse:
    clusters = await CaseClusterService(db).clusters()
    return CaseClusterResponse(
        clusters=[CaseClusterOut(**c) for c in clusters],
        total_clusters=len(clusters),
        disclaimer=settings.disclaimer,
    )


@router.get("/cases/{case_id}", response_model=CaseOut)
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)) -> CaseOut:
    stmt = select(Case).where(Case.case_id == case_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    priority = await CasePriorityService(db).score_case(case)
    return _case_out_with_priority(case, priority)


@router.get("/cases/{case_id}/summary", response_model=CaseSummaryOut)
async def get_case_summary(case_id: str, db: AsyncSession = Depends(get_db)) -> CaseSummaryOut:
    stmt = select(Case).where(Case.case_id == case_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    summary = await AnalystSummaryService(db).build_case_summary(case)
    return CaseSummaryOut(
        **summary,
        disclaimer=settings.disclaimer,
    )


@router.post("/cases/{case_id}/feedback/decision", response_model=AnalystDecisionOut)
async def submit_case_feedback_decision(
    case_id: str,
    request: AnalystDecisionIn,
    db: AsyncSession = Depends(get_db),
) -> AnalystDecisionOut:
    case = await db.scalar(select(Case).where(Case.case_id == case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        row = await FeedbackService(db).add_decision(
            case_id=case_id,
            analyst_id=request.analyst_id,
            analyst_role=request.analyst_role,
            decision_type=request.decision_type,
            notes=request.notes,
            corrected_risk_score=request.corrected_risk_score,
        )
    except DecisionCapError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AnalystDecisionOut(
        feedback_id=row.feedback_id,
        case_id=row.case_id,
        analyst_id=row.analyst_id,
        analyst_role=parse_decision_role(row.notes),
        decision_weight=decision_weight_for_notes(row.notes),
        decision_type=parse_decision_type(row.notes),
        is_false_positive=row.is_false_positive,
        corrected_risk_score=row.corrected_risk_score,
        notes=row.notes,
        created_at=row.created_at,
    )


@router.get("/cases/{case_id}/feedback/decision", response_model=list[AnalystDecisionOut])
async def list_case_feedback_decisions(
    case_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AnalystDecisionOut]:
    case = await db.scalar(select(Case).where(Case.case_id == case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    rows = await FeedbackService(db).list_for_case(case_id, limit=limit)
    return [
        AnalystDecisionOut(
            feedback_id=row.feedback_id,
            case_id=row.case_id,
            analyst_id=row.analyst_id,
            analyst_role=parse_decision_role(row.notes),
            decision_weight=decision_weight_for_notes(row.notes),
            decision_type=parse_decision_type(row.notes),
            is_false_positive=row.is_false_positive,
            corrected_risk_score=row.corrected_risk_score,
            notes=row.notes,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/feedback/labels")
async def feedback_labels(
    case_ids: str = Query(description="Comma-separated list of case IDs (max 200)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return analyst decision labels for each requested case ID."""
    ids = [cid.strip() for cid in case_ids.split(",") if cid.strip()][:200]
    if not ids:
        return {}

    from app.models.feedback import AnalystFeedback

    rows = (
        await db.scalars(
            select(AnalystFeedback).where(AnalystFeedback.case_id.in_(ids))
        )
    ).all()

    out: dict[str, dict] = {}
    for row in rows:
        dt = parse_decision_type(row.notes)
        if not dt:
            continue
        bucket = out.setdefault(row.case_id, {"labels": set(), "count": 0})
        bucket["labels"].add(dt)
        bucket["count"] += 1

    return {
        cid: {"labels": sorted(v["labels"]), "count": v["count"]}
        for cid, v in out.items()
    }

@router.post("/cases/recompute-authority")
async def recompute_case_authority(
    limit: int = Query(default=200, ge=1, le=1000),
    dry_run: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Recompute historical case scores using current source authority weighting.

    This normalizes cases created before source-tier boosts existed, ensuring
    older FBI, Interpol, NamUs, and CourtListener cases reflect the current
    scoring policy.
    """
    result = await CaseAuthorityNormalizationService(db).recompute_cases(limit=limit, dry_run=dry_run)
    return {
        "status": "processed",
        "result": result,
        "disclaimer": settings.disclaimer,
    }
