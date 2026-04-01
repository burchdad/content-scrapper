"""Explainability service for case analysis breakdown and analyst review."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.feedback import AnalystFeedback
from app.models.signal import Signal
from app.services.case_priority_service import CasePriorityService
from app.services.feedback_service import parse_decision_type
from app.services.source_tier import source_impact_summary


class ExplainabilityService:
    """Generates detailed per-case explainability data for analyst review."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def case_explainability(self, case_id: str) -> dict:
        """
        Generate detailed explainability breakdown for a case.

        Returns:
            dict with:
            - case_id, risk_score, system_confidence, status
            - signal_contributions: [{"type", "label", "confidence", "evidence", "weight_pct"}]
            - confidence_breakdown: {"signal_avg", "entity_confidence", "diversity_bonus", "calibration_penalty"}
            - feedback_summary: {"feedback_count", "false_positive_rate", "avg_correction", "recent_feedback": [...]}
            - timestamp
        """
        case_stmt = select(Case).where(Case.case_id == case_id)
        case = await self.db.scalar(case_stmt)
        if not case:
            return {"error": f"Case {case_id} not found"}

        # Fetch signals for this case
        signal_stmt = select(Signal).where(Signal.signal_id.in_(case.signal_ids or []))
        signals = (await self.db.scalars(signal_stmt)).all()

        # Calculate signal contributions
        signal_contributions = []
        if signals:
            total_confidence = sum(s.confidence for s in signals)
            for sig in signals:
                weight_pct = round((sig.confidence / total_confidence * 100) if total_confidence > 0 else 0, 1)
                signal_contributions.append(
                    {
                        "signal_type": sig.signal_type,
                        "label": sig.label,
                        "confidence": round(sig.confidence, 3),
                        "evidence": sig.evidence[:200],  # truncate
                        "source_name": sig.source_name or "unknown",
                        "weight_pct": weight_pct,
                    }
                )

        # Confidence breakdown (estimated from formula: 0.7*signal + 0.25*entity + 0.05*diversity - penalty)
        avg_signal_conf = sum(s.confidence for s in signals) / len(signals) if signals else 0.0
        confidence_breakdown = {
            "signal_avg": round(avg_signal_conf, 3),
            "signal_weight": 0.7,  # weight in formula
            "entity_confidence": round(0.5, 3),  # approximate
            "entity_weight": 0.25,
            "diversity_bonus": round(0.05 if len(signals) > 1 else 0.0, 3),
            "diversity_weight": 0.05,
            "calibration_penalty": round(0.0, 3),  # estimated
            "final_system_confidence": round(case.system_confidence, 3),
        }

        # Feedback summary
        fb_stmt = select(AnalystFeedback).where(AnalystFeedback.case_id == case.case_id).order_by(
            AnalystFeedback.created_at.desc()
        )
        feedback_rows = (await self.db.scalars(fb_stmt)).all()

        recent_fbs = []
        decision_counts = {
            "confirm_convergence": 0,
            "reject_correlation": 0,
            "mark_high_priority": 0,
            "unlabeled": 0,
        }
        for fb in feedback_rows[:5]:  # last 5 feedbacks
            decision_type = parse_decision_type(fb.notes)
            recent_fbs.append(
                {
                    "analyst_id": fb.analyst_id,
                    "decision_type": decision_type,
                    "is_false_positive": fb.is_false_positive,
                    "corrected_risk_score": fb.corrected_risk_score,
                    "notes": fb.notes or "",
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                }
            )

        total_fb = len(feedback_rows)
        fp_count = sum(1 for fb in feedback_rows if fb.is_false_positive)
        fp_rate = round(fp_count / total_fb, 3) if total_fb > 0 else 0.0

        for fb in feedback_rows:
            decision_type = parse_decision_type(fb.notes)
            if decision_type:
                decision_counts[decision_type] = decision_counts.get(decision_type, 0) + 1
            else:
                decision_counts["unlabeled"] = decision_counts.get("unlabeled", 0) + 1

        corrections = [fb.corrected_risk_score for fb in feedback_rows if fb.corrected_risk_score is not None]
        avg_correction = round(sum(corrections) / len(corrections), 1) if corrections else None

        feedback_summary = {
            "feedback_count": total_fb,
            "false_positive_count": fp_count,
            "false_positive_rate": fp_rate,
            "avg_corrected_risk_score": avg_correction,
            "decision_counts": decision_counts,
            "recent_feedback": recent_fbs,
        }

        # Source impact: authority tier analysis across all signals.
        source_names = [s.source_name for s in signals]
        source_impact = source_impact_summary(source_names)
        priority = await CasePriorityService(self.db).score_case(case)
        metadata = case.extra_metadata or {}
        stored_calibration = (
            ((metadata.get("authority_normalization") or {}).get("calibration"))
            or metadata.get("score_calibration")
            or {}
        )
        confidence_breakdown.update(
            {
                "raw_score_before_calibration": round(float(stored_calibration.get("raw_score_before_calibration", 0.0)), 2),
                "source_class_cap": stored_calibration.get("source_class_cap"),
                "confidence_cap": stored_calibration.get("confidence_cap"),
                "reference_only_penalty": round(float(stored_calibration.get("reference_only_penalty", 0.0)), 2),
                "corroboration_boost": round(float(stored_calibration.get("corroboration_boost", 0.0)), 2),
                "cross_source_unlock": stored_calibration.get("cross_source_unlock"),
                "final_risk_score": round(float(stored_calibration.get("final_risk_score", case.risk_score or 0.0)), 2),
            }
        )

        return {
            "case_id": case_id,
            "case_status": case.status,
            "risk_score": round(case.risk_score, 1),
            "system_confidence": round(case.system_confidence, 3),
            "signal_count": len(signals),
            "signal_contributions": signal_contributions,
            "confidence_breakdown": confidence_breakdown,
            "feedback_summary": feedback_summary,
            "source_impact": source_impact,
            "score_calibration": stored_calibration,
            "priority": priority,
            "explanation": case.explanation[:500] if case.explanation else "",
            "entity_ids": case.entity_ids or [],
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
            "disclaimer": case.disclaimer,
        }

    async def case_feedback_history(self, case_id: str, days: int = 30) -> dict:
        """Get feedback history for a case over the past N days."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        fb_stmt = (
            select(AnalystFeedback)
            .where(AnalystFeedback.case_id == case_id)
            .where(AnalystFeedback.created_at >= cutoff_date)
            .order_by(AnalystFeedback.created_at.asc())
        )
        feedbacks = (await self.db.scalars(fb_stmt)).all()

        history = []
        for fb in feedbacks:
            history.append(
                {
                    "feedback_id": fb.feedback_id,
                    "analyst_id": fb.analyst_id,
                    "decision_type": parse_decision_type(fb.notes),
                    "is_false_positive": fb.is_false_positive,
                    "corrected_risk_score": fb.corrected_risk_score,
                    "notes": fb.notes or "",
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                }
            )

        return {
            "case_id": case_id,
            "days": days,
            "feedback_count": len(feedbacks),
            "history": history,
        }
