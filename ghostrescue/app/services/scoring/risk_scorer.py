from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import RiskScoreDetail, RiskScoreOut, SignalOut
from app.services.nlp.pattern_rules import PATTERN_RULES
from app.services.source_tier import (
    authority_boost_for_sources,
    classify_source_class,
    confidence_boost_for_sources,
)

logger = get_logger(__name__)
settings = get_settings()

_SIGNAL_WEIGHT_MAP: dict[str, float] = {rule.signal_type: rule.weight for rule in PATTERN_RULES}

_PERSISTED_SIGNAL_WEIGHT_OVERRIDES: dict[str, float] = {
    # Ingestion/reference signals.
    "law_enforcement_hit": 0.78,
    "law_enforcement_report": 0.62,
    "law_enforcement_reference": 0.58,
    "victim_interview_match": 0.62,
    "missing_person": 0.56,
    "legal_reference": 0.28,
    "trafficking_indicator": 0.46,
    "sex_trafficking_indicator": 0.43,
    "labor_trafficking_indicator": 0.40,
    "financial_crime": 0.32,
    "drug_trafficking": 0.42,
    "violent_crime": 0.48,
    "fugitive": 0.44,
    "terrorism": 0.70,
    # Persisted analytic / synthetic signals already present in the database.
    "financial_transfer_alert": 0.34,
    "money_transfer_pattern": 0.28,
    "coercion_language_detected": 0.36,
    "isolation_behavior": 0.24,
    "document_fraud_detected": 0.28,
    "border_crossing_anomaly": 0.26,
    "false_identity_detected": 0.26,
    "debt_bondage_pattern": 0.34,
    "travel_document_anomaly": 0.24,
    "smuggling_indicator": 0.34,
    "ngo_report": 0.16,
}

_SIGNAL_WEIGHT_MAP.update(_PERSISTED_SIGNAL_WEIGHT_OVERRIDES)

_RISK_BANDS: list[tuple[float, str]] = [
    (80.0, "critical"),
    (60.0, "high"),
    (35.0, "medium"),
    (0.0, "low"),
]

_SOURCE_CLASS_BASE_CAPS: dict[str, tuple[float, float]] = {
    "law_enforcement_direct": (95.0, 0.92),
    "reference_registry": (70.0, 0.75),
    "legal_public_record": (60.0, 0.72),
    "osint_news_social": (65.0, 0.70),
    "synthetic_test": (25.0, 0.40),
}

_SOURCE_CLASS_PAIR_BOOSTS: dict[frozenset[str], float] = {
    frozenset({"law_enforcement_direct", "law_enforcement_direct"}): 8.0,
    frozenset({"law_enforcement_direct", "osint_news_social"}): 7.0,
    frozenset({"law_enforcement_direct", "reference_registry"}): 6.0,
    frozenset({"law_enforcement_direct", "legal_public_record"}): 5.0,
    frozenset({"reference_registry", "osint_news_social"}): 3.0,
    frozenset({"reference_registry", "legal_public_record"}): 2.0,
    frozenset({"legal_public_record", "osint_news_social"}): 2.0,
}

_SOURCE_CLASS_PRIORITY: list[str] = [
    "law_enforcement_direct",
    "reference_registry",
    "legal_public_record",
    "osint_news_social",
    "synthetic_test",
]


class RiskScorer:
    """
    Multi-factor risk scorer.

    Combines:
      • NLP signal weights × confidence
      • Entity match confidence modifier
      • Signal frequency recurrence bonus

    Outputs risk_score (0–100), risk_band, confidence_score (0–1),
    per-factor breakdown, and a human-readable explanation.

    All outputs include the compliance disclaimer.
    """

    def score(
        self,
        signals: list[SignalOut],
        entity_match_confidence: float = 1.0,
        signal_frequency_bonus: float = 0.0,
        calibration_penalty: float = 0.0,
        source_names: list[str | None] | None = None,
        usages: list[str | None] | None = None,
    ) -> RiskScoreOut:
        if not signals:
            return RiskScoreOut(
                risk_score=0.0,
                risk_band="low",
                confidence_score=0.0,
                system_confidence=0.0,
                factors=[],
                explanation=(
                    "No signals detected. Record does not meet triage threshold. "
                    "Human review still recommended for high-priority queues."
                ),
                disclaimer=settings.disclaimer,
            )

        factors: list[RiskScoreDetail] = []
        raw_score = 0.0

        for signal in signals:
            weight = _SIGNAL_WEIGHT_MAP.get(signal.signal_type, 0.10)
            contribution = round(weight * signal.confidence * 100, 2)
            raw_score += contribution
            factors.append(
                RiskScoreDetail(
                    factor=signal.signal_type,
                    contribution=contribution,
                    notes=f'{signal.label} — evidence: «{signal.evidence}»',
                )
            )

        # Entity match confidence modifier (±5 pts max)
        match_modifier = round((entity_match_confidence - 0.5) * 10, 2)
        if match_modifier != 0:
            raw_score += match_modifier
            factors.append(
                RiskScoreDetail(
                    factor="entity_match_confidence",
                    contribution=match_modifier,
                    notes=f"Entity match confidence modifier (confidence={entity_match_confidence:.2f})",
                )
            )

        # Frequency bonus (recurrence of same signals across sources, max +10)
        recurrence_boost = 0.0
        if signal_frequency_bonus > 0:
            recurrence_boost = round(min(signal_frequency_bonus * 5.0, 10.0), 2)
            raw_score += recurrence_boost
            factors.append(
                RiskScoreDetail(
                    factor="signal_frequency",
                    contribution=recurrence_boost,
                    notes=f"Signal recurrence bonus (×{signal_frequency_bonus:.1f} occurrences)",
                )
            )

        raw_score = round(min(100.0, max(0.0, raw_score)), 2)
        confidence_score = round(sum(s.confidence for s in signals) / len(signals), 3)
        diversity_bonus = min(0.2, len({s.signal_type for s in signals}) * 0.03)
        system_confidence = round(
            max(0.0, min(1.0, confidence_score * 0.7 + entity_match_confidence * 0.25 + diversity_bonus - calibration_penalty)),
            3,
        )

        src_names = source_names or [getattr(s, "source_name", None) for s in signals]
        usage_values = usages or [getattr(s, "usage", None) for s in signals]
        source_classes = [classify_source_class(name) for name in src_names if name]
        unique_sources = sorted({(name or "unknown").strip().lower() for name in src_names if name})
        unique_source_count = len(unique_sources)
        law_enforcement_source_count = sum(
            1 for name in unique_sources if classify_source_class(name) == "law_enforcement_direct"
        )
        authority_classes = sorted(set(source_classes))
        highest_source_class = self._highest_source_class(authority_classes)

        # Source authority boost.
        authority_risk_boost = authority_boost_for_sources(src_names)
        authority_conf_boost = confidence_boost_for_sources(src_names)
        risk_score = raw_score
        if authority_risk_boost > 0:
            risk_score = round(min(100.0, risk_score + authority_risk_boost), 2)
            factors.append(
                RiskScoreDetail(
                    factor="source_authority_boost",
                    contribution=authority_risk_boost,
                    notes=f"Source tier authority boost (+{authority_risk_boost:.1f} pts)",
                )
            )
        if authority_conf_boost > 0:
            system_confidence = round(min(1.0, system_confidence + authority_conf_boost), 3)

        corroboration_boost = self._corroboration_boost(
            authority_classes,
            unique_source_count,
            recurrence_boost,
            law_enforcement_source_count,
        )
        if corroboration_boost > 0:
            risk_score = round(min(100.0, risk_score + corroboration_boost), 2)
            system_confidence = round(min(1.0, system_confidence + min(0.06, corroboration_boost / 100)), 3)
            factors.append(
                RiskScoreDetail(
                    factor="corroboration_boost",
                    contribution=corroboration_boost,
                    notes=f"Cross-source corroboration boost from {unique_source_count} independent sources",
                )
            )

        reference_penalty = self._reference_only_penalty(usage_values, authority_classes, unique_source_count)
        if reference_penalty > 0:
            risk_score = round(max(0.0, risk_score - reference_penalty), 2)
            system_confidence = round(max(0.0, system_confidence - min(0.10, reference_penalty / 100)), 3)
            factors.append(
                RiskScoreDetail(
                    factor="reference_only_penalty",
                    contribution=-reference_penalty,
                    notes="Reference-only sources require corroboration before top-tier escalation",
                )
            )

        risk_cap, confidence_cap, unlock_label = self._calibration_caps(
            source_classes=authority_classes,
            unique_source_count=unique_source_count,
            recurrence_boost=recurrence_boost,
            law_enforcement_source_count=law_enforcement_source_count,
        )
        capped_risk_score = round(min(risk_score, risk_cap), 2)
        capped_system_confidence = round(min(system_confidence, confidence_cap), 3)
        if capped_risk_score < risk_score:
            factors.append(
                RiskScoreDetail(
                    factor="source_class_cap",
                    contribution=round(capped_risk_score - risk_score, 2),
                    notes=f"{highest_source_class.replace('_', ' ')} cap applied at {risk_cap:.1f}",
                )
            )
        risk_score = capped_risk_score
        system_confidence = capped_system_confidence

        risk_band = self._band(risk_score)
        calibration = {
            "raw_score_before_calibration": raw_score,
            "authority_risk_boost": authority_risk_boost,
            "authority_confidence_boost": authority_conf_boost,
            "corroboration_boost": corroboration_boost,
            "reference_only_penalty": reference_penalty,
            "source_class_cap": risk_cap,
            "confidence_cap": confidence_cap,
            "cross_source_unlock": unlock_label,
            "final_risk_score": risk_score,
            "final_system_confidence": system_confidence,
            "source_classes": authority_classes,
            "highest_source_class": highest_source_class,
            "unique_source_count": unique_source_count,
            "recurrence_boost": recurrence_boost,
            "calibration_penalty": calibration_penalty,
        }
        explanation = self._explain(risk_score, risk_band, factors, calibration)

        logger.info("Risk scored: %.1f (%s) | %d factors", risk_score, risk_band, len(factors))

        return RiskScoreOut(
            risk_score=risk_score,
            risk_band=risk_band,
            confidence_score=confidence_score,
            system_confidence=system_confidence,
            factors=factors,
            explanation=explanation,
            calibration=calibration,
            disclaimer=settings.disclaimer,
        )

    @staticmethod
    def _band(score: float) -> str:
        for threshold, band in _RISK_BANDS:
            if score >= threshold:
                return band
        return "low"

    def _highest_source_class(self, source_classes: list[str]) -> str:
        for source_class in _SOURCE_CLASS_PRIORITY:
            if source_class in source_classes:
                return source_class
        return "osint_news_social"

    def _corroboration_boost(
        self,
        source_classes: list[str],
        unique_source_count: int,
        recurrence_boost: float,
        law_enforcement_source_count: int,
    ) -> float:
        if unique_source_count <= 1 or not source_classes:
            return 0.0
        boost = 0.0
        unique_classes = sorted(set(source_classes))
        if len(unique_classes) == 1:
            if unique_classes[0] == "law_enforcement_direct" and law_enforcement_source_count >= 2:
                boost += 8.0
            elif unique_source_count >= 2:
                boost += min(3.0, float(unique_source_count - 1))
        else:
            for idx, left in enumerate(unique_classes):
                for right in unique_classes[idx + 1 :]:
                    boost += _SOURCE_CLASS_PAIR_BOOSTS.get(frozenset({left, right}), 1.0)
        if recurrence_boost >= 5.0:
            boost += 2.0
        return round(min(boost, 15.0), 2)

    def _reference_only_penalty(self, usages: list[str | None], source_classes: list[str], unique_source_count: int) -> float:
        normalized_usages = [u for u in usages if u]
        if not normalized_usages:
            return 0.0
        if any(u != "reference_only" for u in normalized_usages):
            return 0.0
        if "law_enforcement_direct" in source_classes and unique_source_count >= 3:
            return 0.0
        if unique_source_count >= 2:
            return 4.0
        return 12.0

    def _calibration_caps(
        self,
        *,
        source_classes: list[str],
        unique_source_count: int,
        recurrence_boost: float,
        law_enforcement_source_count: int,
    ) -> tuple[float, float, str | None]:
        classes = set(source_classes)
        law_enforcement_present = "law_enforcement_direct" in classes
        if law_enforcement_present:
            if (
                len(classes) >= 3
                or unique_source_count >= 3
                or recurrence_boost >= 5.0
                or law_enforcement_source_count >= 2
            ):
                return (95.0, 0.92, "strong_cross_source_unlock")
            if len(classes) >= 2 or unique_source_count >= 2:
                return (85.0, 0.86, "cross_source_unlock")
            return _SOURCE_CLASS_BASE_CAPS["law_enforcement_direct"] + ("standalone_law_enforcement",)

        if "reference_registry" in classes:
            if "osint_news_social" in classes and unique_source_count >= 3:
                return (75.0, 0.78, "multi_source_reference_support")
            return _SOURCE_CLASS_BASE_CAPS["reference_registry"] + ("reference_only_cap",)

        if "legal_public_record" in classes:
            if "osint_news_social" in classes and unique_source_count >= 2:
                return (65.0, 0.74, "legal_context_support")
            return _SOURCE_CLASS_BASE_CAPS["legal_public_record"] + ("legal_record_cap",)

        if "synthetic_test" in classes:
            return _SOURCE_CLASS_BASE_CAPS["synthetic_test"] + ("synthetic_cap",)

        return _SOURCE_CLASS_BASE_CAPS["osint_news_social"] + ("osint_cap",)

    @staticmethod
    def _explain(score: float, band: str, factors: list[RiskScoreDetail], calibration: dict) -> str:
        top = sorted(factors, key=lambda f: f.contribution, reverse=True)[:3]
        factor_text = "; ".join(f.factor.replace("_", " ") for f in top)
        return (
            f"Risk band: {band.upper()} (score: {score:.1f}/100). "
            f"Top contributing factors: {factor_text}. "
            f"Raw score {calibration.get('raw_score_before_calibration', 0.0):.1f}, "
            f"cap {calibration.get('source_class_cap', 0.0):.1f}, "
            f"unlock={calibration.get('cross_source_unlock') or 'none'}. "
            "This is an automated triage signal — human review is required before any enforcement action."
        )
