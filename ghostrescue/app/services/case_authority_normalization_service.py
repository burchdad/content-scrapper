from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.schemas import SignalOut
from app.models.signal import Signal
from app.services.correlation_service import CorrelationService
from app.services.scoring.risk_scorer import RiskScorer
from app.services.source_tier import source_impact_summary
from app.services.trust_service import TrustService


class CaseAuthorityNormalizationService:
    """Recompute historical case scoring using current source authority rules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.scorer = RiskScorer()
        self.correlation = CorrelationService(db)

    async def recompute_cases(self, *, limit: int = 200, dry_run: bool = False) -> dict:
        stmt = select(Case).order_by(Case.updated_at.desc()).limit(limit)
        cases = (await self.db.scalars(stmt)).all()

        penalty = await TrustService(self.db).adaptive_penalty()
        processed = 0
        updated = 0
        skipped = 0
        samples: list[dict] = []

        for case in cases:
            processed += 1
            result = await self._recompute_case(case, penalty=penalty, dry_run=dry_run)
            if result["status"] == "updated":
                updated += 1
                if len(samples) < 5:
                    samples.append(result)
            else:
                skipped += 1

        if not dry_run:
            await self.db.commit()

        return {
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "dry_run": dry_run,
            "samples": samples,
        }

    async def _recompute_case(self, case: Case, *, penalty: float, dry_run: bool) -> dict:
        signal_ids = case.signal_ids or []
        if not signal_ids:
            return {"status": "skipped", "case_id": case.case_id, "reason": "no_signals"}

        signals = (await self.db.scalars(select(Signal).where(Signal.signal_id.in_(signal_ids)))).all()
        if not signals:
            return {"status": "skipped", "case_id": case.case_id, "reason": "signals_missing"}

        signal_outs = [
            SignalOut(
                signal_type=signal.signal_type,
                label=signal.label,
                confidence=signal.confidence,
                evidence=signal.evidence,
                source_name=signal.source_name,
                usage=(signal.extra_metadata or {}).get("usage"),
            )
            for signal in signals
        ]
        source_names = [signal.source_name for signal in signals]
        usages = [(signal.extra_metadata or {}).get("usage") for signal in signals]

        corr_scores = []
        temporal_bursts = []
        for entity_id in case.entity_ids or []:
            corr = await self.correlation.entity_correlation_features(entity_id)
            corr_scores.append(float(corr.get("cross_source_reinforcement", 0.0)))
            temporal_bursts.append(float(corr.get("temporal_burst_24h", 0)))

        entity_match_confidence = max(0.0, min(1.0, 0.5 + (max(corr_scores) / 2 if corr_scores else 0.0)))
        signal_frequency_bonus = max(temporal_bursts) if temporal_bursts else 0.0

        rescored = self.scorer.score(
            signals=signal_outs,
            entity_match_confidence=entity_match_confidence,
            signal_frequency_bonus=signal_frequency_bonus,
            calibration_penalty=penalty,
            source_names=source_names,
            usages=usages,
        )

        old_risk = float(case.risk_score or 0.0)
        old_confidence = float(case.system_confidence or 0.0)
        changed = (
            round(old_risk, 2) != round(rescored.risk_score, 2)
            or round(old_confidence, 3) != round(rescored.system_confidence, 3)
        )
        if not changed:
            return {"status": "skipped", "case_id": case.case_id, "reason": "no_change"}

        impact = source_impact_summary(source_names)
        if not dry_run:
            metadata = dict(case.extra_metadata or {})
            metadata["authority_normalization"] = {
                "normalized_at": datetime.now(UTC).isoformat(),
                "previous_risk_score": old_risk,
                "previous_system_confidence": old_confidence,
                "source_impact": impact,
                "calibration": rescored.calibration,
            }
            case.risk_score = rescored.risk_score
            case.confidence_score = rescored.confidence_score
            case.system_confidence = rescored.system_confidence
            case.explanation = rescored.explanation
            case.extra_metadata = metadata
            case.updated_at = datetime.now(UTC)

        return {
            "status": "updated",
            "case_id": case.case_id,
            "old_risk_score": old_risk,
            "new_risk_score": rescored.risk_score,
            "old_system_confidence": old_confidence,
            "new_system_confidence": rescored.system_confidence,
            "highest_tier": impact.get("highest_tier"),
            "cross_source_unlock": rescored.calibration.get("cross_source_unlock"),
        }