from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.feedback import AnalystFeedback
from app.models.signal import Signal
from app.services.cross_source_linker import CrossSourceLinker
from app.services.feedback_service import decision_weight_for_notes, parse_decision_type
from app.services.source_registry import get_influence_cap
from app.services.source_tier import classify_source_class

_SOURCE_CLASS_PRIORITY = [
    "law_enforcement_direct",
    "reference_registry",
    "legal_public_record",
    "osint_news_social",
    "synthetic_test",
]

_SOURCE_GROUP_DEFAULT_WEIGHT = {
    "polaris": 0.5,
    "ncmec": 0.45,
    "namus": 0.35,
    "courtlistener": 0.25,
    "interpol": 0.2,
    "fbi": 0.2,
    "newsapi": 0.1,
    "gdelt": 0.05,
    "other": 0.0,
    "unknown": 0.0,
}

_US_GEO_HINTS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la",
    "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "california", "texas", "florida", "new york", "illinois", "arizona", "nevada", "washington", "georgia", "ohio",
}


class CasePriorityService:
    """Case-level queue ranking with cross-source corroboration and soft diversity controls."""

    _CORROBORATION_CACHE_TTL_SECONDS = 180
    _CORROBORATION_CACHE_MAX_ENTRIES = 2000
    _corroboration_cache: dict[str, tuple[float, dict]] = {}
    _metrics_lock = threading.Lock()
    _cache_hits = 0
    _cache_misses = 0
    _cache_evictions = 0
    _cache_prunes = 0
    _compute_count = 0
    _compute_total_ms = 0.0
    _cached_latency_count = 0
    _cached_latency_total_ms = 0.0

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @classmethod
    def corroboration_cache_metrics(cls) -> dict:
        with cls._metrics_lock:
            hits = cls._cache_hits
            misses = cls._cache_misses
            evictions = cls._cache_evictions
            prunes = cls._cache_prunes
            compute_count = cls._compute_count
            compute_total_ms = cls._compute_total_ms
            cached_latency_count = cls._cached_latency_count
            cached_latency_total_ms = cls._cached_latency_total_ms
            cache_size = len(cls._corroboration_cache)

        total_lookups = hits + misses
        hit_rate = round(hits / total_lookups, 4) if total_lookups else 0.0
        avg_compute_ms = round(compute_total_ms / compute_count, 3) if compute_count else 0.0
        avg_cached_latency_ms = round(cached_latency_total_ms / cached_latency_count, 3) if cached_latency_count else 0.0
        estimated_time_saved_ms = round(hits * avg_compute_ms, 3)

        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
            "evictions": evictions,
            "prunes": prunes,
            "size": cache_size,
            "ttl_seconds": cls._CORROBORATION_CACHE_TTL_SECONDS,
            "max_entries": cls._CORROBORATION_CACHE_MAX_ENTRIES,
            "avg_compute_ms": avg_compute_ms,
            "avg_cached_latency_ms": avg_cached_latency_ms,
            "estimated_time_saved_ms": estimated_time_saved_ms,
        }

    @classmethod
    def corroboration_quality_metrics(cls) -> dict:
        now = time.time()
        tier_distribution = {
            "tier_0_single_source": 0,
            "tier_1_multi_signal_same_source": 0,
            "tier_2_multi_case_same_family": 0,
            "tier_2_5_weak_multi_family_convergence": 0,
            "tier_3_multi_family_corroborated": 0,
            "tier_4_high_confidence_convergence": 0,
            "unknown": 0,
        }

        with cls._metrics_lock:
            active_payloads: list[dict] = []
            expired_keys = [k for k, (exp, _) in cls._corroboration_cache.items() if exp <= now]
            for key in expired_keys:
                cls._corroboration_cache.pop(key, None)
            if expired_keys:
                cls._cache_prunes += len(expired_keys)

            for _, (_, payload) in cls._corroboration_cache.items():
                active_payloads.append(payload)

        if not active_payloads:
            return {
                "samples": 0,
                "avg_source_families": 0.0,
                "avg_linked_cases": 0.0,
                "avg_confidence": 0.0,
                "tier_distribution": tier_distribution,
            }

        source_families_total = 0
        linked_cases_total = 0
        confidence_total = 0.0
        for payload in active_payloads:
            source_families_total += int(payload.get("source_families") or 0)
            linked_cases_total += int(payload.get("linked_cases") or 0)
            confidence_total += float(payload.get("confidence") or 0.0)
            tier = payload.get("corroboration_tier") or "unknown"
            if tier not in tier_distribution:
                tier = "unknown"
            tier_distribution[tier] += 1

        samples = len(active_payloads)
        return {
            "samples": samples,
            "avg_source_families": round(source_families_total / samples, 3),
            "avg_linked_cases": round(linked_cases_total / samples, 3),
            "avg_confidence": round(confidence_total / samples, 3),
            "tier_distribution": tier_distribution,
        }

    async def score_cases(self, cases: list[Case], *, apply_saturation: bool = True) -> dict[str, dict]:
        if not cases:
            return {}

        case_signal_map = await self._load_case_signals(cases)
        feedback_map = await self._load_case_feedback(cases)
        all_signals = [signal for signals in case_signal_map.values() for signal in signals]
        if len(all_signals) > 240:
            all_signals = sorted(all_signals, key=lambda s: self._to_utc(s.detected_at), reverse=True)[:240]
        signal_to_case: dict[str, str] = {}
        for case in cases:
            for signal_id in case.signal_ids or []:
                signal_to_case[signal_id] = case.case_id

        linker = CrossSourceLinker(self.db)

        scored: dict[str, dict] = {}
        dominant_class_counts: dict[str, int] = {}

        request_cache: dict[str, dict] = {}

        for case in cases:
            signals = case_signal_map.get(case.case_id, [])
            feedbacks = feedback_map.get(case.case_id, [])
            scored_case = self._score_case(
                case,
                signals,
                feedbacks,
                all_signals,
                signal_to_case,
                linker,
                request_cache,
            )
            scored[case.case_id] = scored_case
            dom = scored_case["dominant_source_class"]
            dominant_class_counts[dom] = dominant_class_counts.get(dom, 0) + 1

        source_weight_by_group = self._adaptive_source_weights(cases=cases, scored=scored, case_signal_map=case_signal_map)
        if source_weight_by_group:
            for case in cases:
                data = scored[case.case_id]
                groups = self._source_groups_for_case(case, case_signal_map)
                if not groups:
                    continue
                source_weight_bonus = round(sum(source_weight_by_group.get(g, 0.0) for g in groups) / len(groups), 2)
                source_weight_bonus = max(-2.5, min(6.0, source_weight_bonus))
                data["source_weight_bonus"] = source_weight_bonus
                data["priority_score"] = round(max(0.0, min(100.0, data["priority_score"] + source_weight_bonus)), 2)
                data["priority_band"] = self._priority_band(data["priority_score"])
                data["priority_explanation"] = self._build_priority_explanation(data)

        if apply_saturation:
            focus_cases = [
                data
                for data in scored.values()
                if data["independent_source_families"] <= 1 and data["base_risk"] >= 75.0
            ]
            focus_counts: dict[str, int] = {}
            for data in focus_cases:
                dom = data["dominant_source_class"]
                focus_counts[dom] = focus_counts.get(dom, 0) + 1
            focus_total = max(1, len(focus_cases))

            for case in cases:
                data = scored[case.case_id]
                dom = data["dominant_source_class"]
                ratio = focus_counts.get(dom, 0) / focus_total
                families = data["independent_source_families"]
                penalty = 0.0
                if families <= 1 and data["base_risk"] >= 75.0 and ratio > 0.30:
                    penalty = min(14.0, (ratio - 0.30) * 50.0)
                    if dom == "law_enforcement_direct":
                        penalty = round(min(16.0, penalty * 1.35), 2)
                data["saturation_penalty"] = penalty
                data["priority_score"] = round(max(0.0, min(100.0, data["priority_score"] - penalty)), 2)
                data["priority_band"] = self._priority_band(data["priority_score"])
                data["priority_explanation"] = self._build_priority_explanation(data)

        return scored

    async def score_case(self, case: Case) -> dict:
        context_stmt = select(Case).order_by(Case.updated_at.desc()).limit(30)
        context_cases = (await self.db.scalars(context_stmt)).all()
        by_id = {c.case_id: c for c in context_cases}
        if case.case_id not in by_id:
            context_cases.append(case)
        scored = await self.score_cases(context_cases, apply_saturation=True)
        return scored.get(case.case_id, {})

    async def _load_case_signals(self, cases: list[Case]) -> dict[str, list[Signal]]:
        case_signal_ids: dict[str, set[str]] = {c.case_id: set(c.signal_ids or []) for c in cases}
        all_signal_ids = sorted({sid for ids in case_signal_ids.values() for sid in ids})
        if not all_signal_ids:
            return {c.case_id: [] for c in cases}

        rows = (await self.db.scalars(select(Signal).where(Signal.signal_id.in_(all_signal_ids)))).all()
        by_id = {s.signal_id: s for s in rows}

        case_signals: dict[str, list[Signal]] = {}
        for case in cases:
            case_signals[case.case_id] = [by_id[sid] for sid in (case.signal_ids or []) if sid in by_id]
        return case_signals

    async def _load_case_feedback(self, cases: list[Case]) -> dict[str, list[AnalystFeedback]]:
        case_ids = [c.case_id for c in cases]
        if not case_ids:
            return {}
        rows = (await self.db.scalars(select(AnalystFeedback).where(AnalystFeedback.case_id.in_(case_ids)))).all()
        out: dict[str, list[AnalystFeedback]] = {c.case_id: [] for c in cases}
        for row in rows:
            out.setdefault(row.case_id, []).append(row)
        return out

    def _score_case(
        self,
        case: Case,
        signals: list[Signal],
        feedbacks: list[AnalystFeedback],
        all_signals: list[Signal],
        signal_to_case: dict[str, str],
        linker: CrossSourceLinker,
        request_cache: dict[str, dict],
    ) -> dict:
        base_risk = float(case.risk_score or 0.0)
        source_classes = [classify_source_class(s.source_name) for s in signals if s.source_name]
        unique_classes = sorted(set(source_classes))
        independent_families = len(unique_classes)
        dominant_source_class = self._dominant_class(source_classes)
        case_signal_ids = {signal.signal_id for signal in signals}

        corroboration_strength, corroboration_bonus = self._cross_source_corroboration(signals, unique_classes)
        corroboration = self._independent_corroboration(
            case=case,
            linker=linker,
            signals=signals,
            all_signals=all_signals,
            case_signal_ids=case_signal_ids,
            signal_to_case=signal_to_case,
            request_cache=request_cache,
        )
        external_link_count = corroboration["linked_cases"]
        external_classes = corroboration["source_classes"]
        external_link_bonus = self._corroboration_strength_bonus(corroboration)
        diversity_bonus = self._diversity_bonus(unique_classes)
        recency_bonus = self._recency_bonus(signals)
        feedback_bonus = self._feedback_bonus(feedbacks)

        # Trust-level cap: low-trust / unvalidated signals cannot fully drive bonuses
        trust_multiplier = self._trust_level_multiplier(signals)
        corroboration_bonus = round(corroboration_bonus * trust_multiplier, 2)
        external_link_bonus = round(external_link_bonus * trust_multiplier, 2)
        diversity_bonus = round(diversity_bonus * trust_multiplier, 2)

        priority_score = round(
            max(
                0.0,
                min(
                    100.0,
                    base_risk + corroboration_bonus + external_link_bonus + diversity_bonus + recency_bonus + feedback_bonus,
                ),
            ),
            2,
        )

        scored = {
            "case_id": case.case_id,
            "base_risk": round(base_risk, 2),
            "priority_score": priority_score,
            "priority_band": self._priority_band(priority_score),
            "corroboration_bonus": corroboration_bonus,
            "corroboration_strength": corroboration_strength,
            "independent_corroboration": corroboration,
            "corroboration_tier": corroboration.get("corroboration_tier"),
            "external_link_count": external_link_count,
            "external_link_classes": external_classes,
            "external_link_bonus": external_link_bonus,
            "diversity_bonus": diversity_bonus,
            "recency_bonus": recency_bonus,
            "analyst_feedback_bonus": feedback_bonus,
            "trust_level_multiplier": round(trust_multiplier, 3),
            "source_weight_bonus": 0.0,
            "saturation_penalty": 0.0,
            "independent_source_families": independent_families,
            "source_classes": unique_classes,
            "dominant_source_class": dominant_source_class,
            "priority_explanation": "",
        }
        scored["priority_explanation"] = self._build_priority_explanation(scored)
        return scored

    def _cross_source_corroboration(self, signals: list[Signal], unique_classes: list[str]) -> tuple[str, float]:
        if len(unique_classes) <= 1 or len(signals) <= 1:
            return ("none", 0.0)

        pair_links = 0
        for i, left in enumerate(signals):
            left_class = classify_source_class(left.source_name)
            left_dt = self._to_utc(left.detected_at)
            for right in signals[i + 1 :]:
                right_class = classify_source_class(right.source_name)
                if left_class == right_class:
                    continue
                right_dt = self._to_utc(right.detected_at)
                temporal_ok = abs((left_dt - right_dt).total_seconds()) <= 30 * 86400
                type_ok = left.signal_type == right.signal_type
                geo_ok = self._geo_overlap(left, right)
                if temporal_ok and (type_ok or geo_ok):
                    pair_links += 1

        bonus = min(14.0, pair_links * 2.0)
        if "law_enforcement_direct" in unique_classes and len(unique_classes) >= 2:
            bonus += 4.0
        if len(unique_classes) >= 3:
            bonus += 2.0
        bonus = round(min(18.0, bonus), 2)

        if bonus >= 12:
            strength = "strong"
        elif bonus >= 6:
            strength = "moderate"
        elif bonus > 0:
            strength = "light"
        else:
            strength = "none"
        return (strength, bonus)

    def _diversity_bonus(self, unique_classes: list[str]) -> float:
        if not unique_classes:
            return 0.0
        classes = set(unique_classes)
        bonus = max(0.0, (len(classes) - 1) * 2.5)
        if {"law_enforcement_direct", "reference_registry"}.issubset(classes):
            bonus += 2.0
        if {"law_enforcement_direct", "osint_news_social"}.issubset(classes):
            bonus += 2.0
        return round(min(10.0, bonus), 2)

    def _recency_bonus(self, signals: list[Signal]) -> float:
        if not signals:
            return 0.0
        latest = max((self._to_utc(s.detected_at) for s in signals), default=None)
        if latest is None:
            return 0.0
        age_days = max(0.0, (datetime.now(UTC) - latest).total_seconds() / 86400)
        if age_days <= 3:
            return 5.0
        if age_days <= 14:
            return 3.0
        if age_days <= 30:
            return 1.5
        if age_days <= 90:
            return 0.5
        return 0.0

    def _feedback_bonus(self, feedbacks: list[AnalystFeedback]) -> float:
        if not feedbacks:
            return 0.0
        valid = 0.0
        false_pos = 0.0
        confirmed = 0.0
        high_priority_marks = 0.0
        for fb in feedbacks:
            weight = decision_weight_for_notes(fb.notes)
            if fb.is_false_positive:
                false_pos += weight
            else:
                valid += weight
            decision_type = parse_decision_type(fb.notes)
            if decision_type == "confirm_convergence":
                confirmed += weight
            elif decision_type == "mark_high_priority":
                high_priority_marks += weight

        bonus = min(6.0, valid * 1.5) - min(10.0, false_pos * 2.2)
        bonus += min(4.0, confirmed * 0.9)
        bonus += min(8.0, high_priority_marks * 1.8)
        return round(bonus, 2)

    def _trust_level_multiplier(self, signals: list[Signal]) -> float:
        """Compute an influence multiplier (0.0–1.0) for the signal set.

        Signals from low-trust (unvalidated / staged) sources are capped so they
        cannot fully drive corroboration and diversity bonuses.  The multiplier is
        the weighted average of per-source influence caps, where high-cap sources
        contribute more weight.
        """
        if not signals:
            return 1.0
        total_cap = 0.0
        total_weight = 0.0
        for sig in signals:
            cap = get_influence_cap(sig.source_name or "unknown")
            # Use cap itself as the weight so authoritative sources dominate
            total_cap += cap * cap
            total_weight += cap
        return min(1.0, total_cap / total_weight) if total_weight > 0 else 1.0

    def _dominant_class(self, source_classes: list[str]) -> str:
        if not source_classes:
            return "osint_news_social"
        counts: dict[str, int] = {}
        for source_class in source_classes:
            counts[source_class] = counts.get(source_class, 0) + 1
        top_count = max(counts.values())
        tied = [source_class for source_class, count in counts.items() if count == top_count]
        for preferred in _SOURCE_CLASS_PRIORITY:
            if preferred in tied:
                return preferred
        return tied[0]

    def _priority_band(self, score: float) -> str:
        if score >= 85:
            return "urgent"
        if score >= 70:
            return "high"
        if score >= 50:
            return "medium"
        return "routine"

    def _build_priority_explanation(self, data: dict) -> str:
        convergence = data["independent_corroboration"].get("convergence_explanation") or {}
        geo = convergence.get("geo_overlap") or "none"
        temporal = convergence.get("temporal_overlap") or "none"
        align = ", ".join(convergence.get("signal_alignment") or []) or "none"
        return (
            f"Priority {data['priority_band'].upper()} ({data['priority_score']:.1f}). "
            f"Base risk {data['base_risk']:.1f}, corroboration +{data['corroboration_bonus']:.1f}, "
            f"independent corroboration +{data['external_link_bonus']:.1f} "
            f"({data['independent_corroboration'].get('linked_cases', 0)} linked cases, "
            f"{data['independent_corroboration'].get('source_families', 0)} source families, "
            f"{data['independent_corroboration'].get('strong_matches', 0)} strong matches), "
            f"diversity +{data['diversity_bonus']:.1f}, recency +{data['recency_bonus']:.1f}, "
            f"feedback +{data['analyst_feedback_bonus']:.1f}, source weighting +{data['source_weight_bonus']:.1f}, saturation -{data['saturation_penalty']:.1f}. "
            f"Trust multiplier: {data.get('trust_level_multiplier', 1.0):.2f}. "
            f"Convergence: geo={geo}, temporal={temporal}, alignment={align}. "
            f"Independent source families: {data['independent_source_families']} ({', '.join(data['source_classes']) or 'none'})."
        )

    def _adaptive_source_weights(self, *, cases: list[Case], scored: dict[str, dict], case_signal_map: dict[str, list[Signal]]) -> dict[str, float]:
        source_stats: dict[str, dict[str, float | int]] = {}
        for case in cases:
            case_id = case.case_id
            groups = self._source_groups_for_case(case, case_signal_map)
            if not groups:
                continue
            data = scored.get(case_id) or {}
            tier = str(data.get("corroboration_tier") or "")
            for group in groups:
                bucket = source_stats.setdefault(group, {"cases": 0, "tier_2_5": 0, "tier_3": 0, "tier_4": 0})
                bucket["cases"] = int(bucket["cases"]) + 1
                if tier == "tier_2_5_weak_multi_family_convergence":
                    bucket["tier_2_5"] = int(bucket["tier_2_5"]) + 1
                elif tier == "tier_3_multi_family_corroborated":
                    bucket["tier_3"] = int(bucket["tier_3"]) + 1
                elif tier == "tier_4_high_confidence_convergence":
                    bucket["tier_4"] = int(bucket["tier_4"]) + 1

        weights: dict[str, float] = {}
        for group, bucket in source_stats.items():
            cases_count = max(1, int(bucket["cases"]))
            tier_2_5_rate = float(bucket["tier_2_5"]) / cases_count
            tier_3_rate = float(bucket["tier_3"]) / cases_count
            tier_4_rate = float(bucket["tier_4"]) / cases_count
            baseline = _SOURCE_GROUP_DEFAULT_WEIGHT.get(group, 0.0)
            adaptive = baseline + (tier_2_5_rate * 0.8) + (tier_3_rate * 1.4) + (tier_4_rate * 2.2)
            # Mildly suppress very high-volume context sources when no convergence tiers fire.
            if group in {"gdelt", "newsapi"} and tier_3_rate == 0.0 and tier_4_rate == 0.0:
                adaptive -= 0.6
            weights[group] = round(max(-1.5, min(3.5, adaptive)), 3)
        return weights

    def _source_groups_for_case(self, case: Case, case_signal_map: dict[str, list[Signal]]) -> set[str]:
        groups: set[str] = set()
        for signal in case_signal_map.get(case.case_id, []):
            groups.add(self._normalize_source_group(signal.source_name))
        return groups

    def _normalize_source_group(self, source_name: str | None) -> str:
        norm = (source_name or "").strip().lower()
        if not norm:
            return "unknown"
        if norm.startswith("newsapi"):
            return "newsapi"
        if norm.startswith("gdelt"):
            return "gdelt"
        if norm.startswith("polaris"):
            return "polaris"
        if norm.startswith("interpol"):
            return "interpol"
        if norm.startswith("fbi"):
            return "fbi"
        if norm.startswith("namus"):
            return "namus"
        if norm.startswith("ncmec"):
            return "ncmec"
        if norm.startswith("courtlistener") or norm.startswith("court_"):
            return "courtlistener"
        return "other"

    def _independent_corroboration(
        self,
        *,
        case: Case,
        linker: CrossSourceLinker,
        signals: list[Signal],
        all_signals: list[Signal],
        case_signal_ids: set[str],
        signal_to_case: dict[str, str],
        request_cache: dict[str, dict],
    ) -> dict:
        cls = type(self)
        cache_key = self._corroboration_cache_key(case)
        request_cached = request_cache.get(cache_key)
        if request_cached is not None:
            return request_cached

        cached, cached_lookup_ms = self._get_cached_corroboration(cache_key)
        if cached is not None:
            request_cache[cache_key] = cached
            with cls._metrics_lock:
                cls._cached_latency_count += 1
                cls._cached_latency_total_ms += cached_lookup_ms
            return cached

        if not signals:
            empty = {
                "linked_cases": 0,
                "source_families": 0,
                "strong_matches": 0,
                "overlap_density": 0.0,
                "confidence": 0.0,
                "corroboration_tier": "tier_0_single_source",
                "linked_case_ids": [],
                "source_classes": [],
            }
            request_cache[cache_key] = empty
            self._store_cached_corroboration(cache_key, empty)
            return empty

        anchor_signals = sorted(signals, key=lambda s: self._to_utc(s.detected_at), reverse=True)[:4]
        candidates = [candidate for candidate in all_signals if candidate.signal_id not in case_signal_ids][:120]
        compute_start = time.perf_counter()
        corroboration = linker.independent_corroboration(
            anchor_signals=anchor_signals,
            candidate_signals=candidates,
            signal_to_case=signal_to_case,
            max_temporal_days=45,
        )
        compute_ms = (time.perf_counter() - compute_start) * 1000.0
        with cls._metrics_lock:
            cls._compute_count += 1
            cls._compute_total_ms += compute_ms
        request_cache[cache_key] = corroboration
        self._store_cached_corroboration(cache_key, corroboration)
        return corroboration

    def _corroboration_cache_key(self, case: Case) -> str:
        updated = self._to_utc(case.updated_at).isoformat() if case.updated_at else "none"
        return f"{case.case_id}:{updated}"

    def _get_cached_corroboration(self, cache_key: str) -> tuple[dict | None, float]:
        cls = type(self)
        start = time.perf_counter()
        now = time.time()
        cached = cls._corroboration_cache.get(cache_key)
        if not cached:
            with cls._metrics_lock:
                cls._cache_misses += 1
            return None, (time.perf_counter() - start) * 1000.0

        expires_at, payload = cached
        if expires_at <= now:
            cls._corroboration_cache.pop(cache_key, None)
            with cls._metrics_lock:
                cls._cache_misses += 1
                cls._cache_prunes += 1
            return None, (time.perf_counter() - start) * 1000.0

        with cls._metrics_lock:
            cls._cache_hits += 1
        return payload, (time.perf_counter() - start) * 1000.0

    def _store_cached_corroboration(self, cache_key: str, payload: dict) -> None:
        cls = type(self)
        now = time.time()
        ttl = cls._CORROBORATION_CACHE_TTL_SECONDS
        cls._corroboration_cache[cache_key] = (now + ttl, payload)

        if len(cls._corroboration_cache) <= cls._CORROBORATION_CACHE_MAX_ENTRIES:
            return

        expired_keys = [k for k, (exp, _) in cls._corroboration_cache.items() if exp <= now]
        for key in expired_keys:
            cls._corroboration_cache.pop(key, None)
        if expired_keys:
            with cls._metrics_lock:
                cls._cache_prunes += len(expired_keys)

        if len(cls._corroboration_cache) <= cls._CORROBORATION_CACHE_MAX_ENTRIES:
            return

        oldest_keys = sorted(cls._corroboration_cache.items(), key=lambda item: item[1][0])
        overflow = len(cls._corroboration_cache) - cls._CORROBORATION_CACHE_MAX_ENTRIES
        for key, _ in oldest_keys[:overflow]:
            cls._corroboration_cache.pop(key, None)
        if overflow > 0:
            with cls._metrics_lock:
                cls._cache_evictions += overflow

    def _corroboration_strength_bonus(self, corroboration: dict) -> float:
        families = int(corroboration.get("source_families") or 0)
        linked_cases = int(corroboration.get("linked_cases") or 0)
        strong_matches = int(corroboration.get("strong_matches") or 0)
        confidence = float(corroboration.get("confidence") or 0.0)

        bonus = min(12.0, families * 2.2)
        bonus += min(8.0, linked_cases * 0.8)
        bonus += min(4.0, strong_matches * 1.2)
        bonus += min(4.0, confidence * 4.0)
        tier = str(corroboration.get("corroboration_tier") or "")
        if tier == "tier_4_high_confidence_convergence":
            bonus += 12.0
        elif tier == "tier_3_multi_family_corroborated":
            bonus += 5.0
        elif tier == "tier_2_5_weak_multi_family_convergence":
            bonus += 2.0
        return round(min(30.0, bonus), 2)

    def _geo_overlap(self, left: Signal, right: Signal) -> bool:
        left_text = f"{left.label or ''} {left.evidence or ''} {left.raw_text_snippet or ''}".lower()
        right_text = f"{right.label or ''} {right.evidence or ''} {right.raw_text_snippet or ''}".lower()
        left_tokens = {t for t in _US_GEO_HINTS if t in left_text}
        right_tokens = {t for t in _US_GEO_HINTS if t in right_text}
        return bool(left_tokens & right_tokens)

    def _to_utc(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
