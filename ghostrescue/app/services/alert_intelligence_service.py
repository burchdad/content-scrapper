import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.alert import Alert
from app.models.case import Case
from app.models.schemas import SignalOut
from app.services.trust_service import TrustService

settings = get_settings()


class AlertIntelligenceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def evaluate_and_create_case(
        self,
        entity_id: str,
        risk_score: float,
        confidence_score: float,
        system_confidence: float,
        explanation: str,
        signals: list[SignalOut],
        correlation: dict,
        score_calibration: dict | None = None,
    ) -> tuple[Case, Alert | None]:
        case = await self._upsert_case(
            entity_id,
            risk_score,
            confidence_score,
            system_confidence,
            explanation,
            signals,
            score_calibration=score_calibration,
        )
        alert = await self._maybe_escalate_alert(case, signals, correlation)
        return case, alert

    async def _upsert_case(
        self,
        entity_id: str,
        risk_score: float,
        confidence_score: float,
        system_confidence: float,
        explanation: str,
        signals: list[SignalOut],
        score_calibration: dict | None = None,
    ) -> Case:
        stmt = select(Case).where(Case.entity_ids.contains([entity_id]))
        result = await self.db.execute(stmt)
        case = result.scalar_one_or_none()

        if not case:
            case = Case(
                case_id=f"case-{uuid.uuid4().hex[:12]}",
                status="under_review",
                risk_score=risk_score,
                confidence_score=confidence_score,
                system_confidence=system_confidence,
                explanation=explanation,
                entity_ids=[entity_id],
                signal_ids=[s.signal_type for s in signals],
                disclaimer=settings.disclaimer,
                extra_metadata={
                    "created_by": "alert_intelligence",
                    "score_calibration": score_calibration or {},
                },
            )
            self.db.add(case)
        else:
            case.risk_score = max(case.risk_score, risk_score)
            case.confidence_score = max(case.confidence_score, confidence_score)
            case.system_confidence = max(case.system_confidence, system_confidence)
            case.explanation = explanation
            case.signal_ids = sorted(set(case.signal_ids + [s.signal_type for s in signals]))
            metadata = dict(case.extra_metadata or {})
            if score_calibration:
                metadata["score_calibration"] = score_calibration
                case.extra_metadata = metadata
            case.updated_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(case)
        return case

    async def _maybe_escalate_alert(
        self,
        case: Case,
        signals: list[SignalOut],
        correlation: dict,
    ) -> Alert | None:
        signal_types = {s.signal_type for s in signals}
        source_diversity = correlation.get("source_diversity", 0)
        cfg = await TrustService(self.db).get_or_create_config()

        severity = None
        reason_codes: list[str] = []

        if case.risk_score >= cfg.risk_critical_threshold and "minor_risk_language" in signal_types and source_diversity >= 2:
            severity = "critical"
            reason_codes.extend(["risk_gt_critical_threshold", "minor_signal_present", "multi_source_entity"])
        elif case.risk_score >= cfg.risk_high_threshold and len(signal_types) >= 2:
            severity = "high"
            reason_codes.extend(["risk_gt_high_threshold", "compound_signal_trigger"])
        elif case.risk_score >= cfg.risk_medium_threshold:
            severity = "medium"
            reason_codes.append("risk_gt_medium_threshold")

        if not severity:
            return None

        case.status = "escalated" if severity in {"high", "critical"} else "under_review"
        case.updated_at = datetime.now(UTC)

        alert = Alert(
            alert_id=f"alert-{uuid.uuid4().hex[:12]}",
            case_id=case.case_id,
            severity=severity,
            message=(
                f"Escalation {severity.upper()}: risk={case.risk_score:.1f}, "
                f"signals={len(signal_types)}, sources={source_diversity}."
            ),
            extra_metadata={
                "reason_codes": reason_codes,
                "signal_types": sorted(signal_types),
                "source_diversity": source_diversity,
            },
        )
        self.db.add(alert)
        await self.db.commit()
        await self.db.refresh(case)
        await self.db.refresh(alert)
        return alert
