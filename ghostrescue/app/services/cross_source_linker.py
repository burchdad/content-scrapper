"""Cross-source entity linker.

Finds potential connections between signals/entities that originate from
different ingestion sources (e.g., NamUs missing persons vs. FBI subjects).

Linking strategies
------------------
1. Geographic overlap  – shared US state or major city tokens in evidence text
2. Temporal proximity  – signals detected within a configurable time window
3. Name token overlap  – shared surname or name fragment across entities

The service returns ranked *link candidates* — NOT confirmed identities.
Every result includes a disclaimer reminding analysts that automated links
require human corroboration.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity
from app.models.signal import Signal
from app.services.source_tier import classify_source, classify_source_class

# ---------------------------------------------------------------------------
# US state / major-city pattern for geographic overlap
# ---------------------------------------------------------------------------

_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
    # state abbreviations
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi",
    "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi",
    "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc",
    "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut",
    "vt", "va", "wa", "wv", "wi", "wy",
}

_MAJOR_CITIES = {
    "new york", "los angeles", "chicago", "houston", "phoenix", "dallas",
    "san antonio", "san diego", "san jose", "austin", "jacksonville",
    "fort worth", "columbus", "charlotte", "indianapolis", "san francisco",
    "seattle", "denver", "nashville", "oklahoma city", "el paso",
    "washington", "las vegas", "louisville", "memphis", "portland",
    "baltimore", "milwaukee", "albuquerque", "tucson", "fresno", "miami",
    "atlanta", "minneapolis", "new orleans", "detroit", "cleveland",
    "tampa", "sacramento", "st. louis", "kansas city", "pittsburgh",
    "orlando", "cincinnati", "richmond", "salt lake city", "boston",
}

_GEO_TOKENS: set[str] = _US_STATES | _MAJOR_CITIES

_GENERIC_SIGNAL_TYPES = {
    "ngo_report",
    "law_enforcement_report",
    "victim_interview_match",
}


def _extract_geo_tokens(text: str) -> set[str]:
    """Extract geographic tokens (states, major cities) from free text."""
    norm = text.lower()
    found: set[str] = set()
    for token in _GEO_TOKENS:
        # word-boundary aware: avoid partial matches inside longer words
        if re.search(r"\b" + re.escape(token) + r"\b", norm):
            found.add(token)
    return found


def _name_tokens(name: str) -> set[str]:
    """Return lowercase word tokens from a canonical name (length ≥ 3)."""
    return {w.lower() for w in re.split(r"[\s,\-]+", name) if len(w) >= 3}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize_source_group(source_name: str | None) -> str:
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


# ---------------------------------------------------------------------------
# CrossSourceLinker
# ---------------------------------------------------------------------------

class CrossSourceLinker:
    """
    Find cross-source intelligence links between signals/entities.

    Parameters
    ----------
    db              AsyncSession
    time_window_days Max age of signals considered for linking (default 90).
    geo_min_overlap Minimum shared geographic tokens to flag geo link (default 1).
    name_min_overlap Minimum shared name tokens to flag name link (default 1).
    min_link_score  Ignore candidates below this score (0–1, default 0.25).
    """

    DISCLAIMER = (
        "Cross-source links are automated pattern matches only. "
        "They do not constitute verified identity or causal connections. "
        "Human analyst review is required before any investigative action."
    )

    def __init__(
        self,
        db: AsyncSession,
        *,
        time_window_days: int = 90,
        geo_min_overlap: int = 1,
        name_min_overlap: int = 1,
        min_link_score: float = 0.25,
    ) -> None:
        self.db = db
        self.time_window = timedelta(days=time_window_days)
        self.geo_min_overlap = geo_min_overlap
        self.name_min_overlap = name_min_overlap
        self.min_link_score = min_link_score

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def find_links(
        self,
        anchor_source_patterns: list[str] | None = None,
        target_source_patterns: list[str] | None = None,
        max_candidates: int = 50,
    ) -> dict:
        """
        Search for cross-source links.

        anchor_source_patterns: sources to use as the "anchor" side
            (e.g., ["namus"] for NamUs missing persons).
        target_source_patterns: sources to link against
            (e.g., ["fbi most wanted"] for FBI subjects).
        When both are None, all sources are considered and any cross-source
        pair is a candidate.
        """
        cutoff = datetime.now(UTC) - self.time_window
        anchor_signals, target_signals = await self._load_signals(
            cutoff, anchor_source_patterns, target_source_patterns
        )

        if not anchor_signals or not target_signals:
            return {
                "links_found": 0,
                "candidates": [],
                "anchor_count": len(anchor_signals),
                "target_count": len(target_signals),
                "disclaimer": self.DISCLAIMER,
            }

        # Load entities for name matching
        entity_ids = {s.entity_id for s in anchor_signals + target_signals if s.entity_id}
        entities: dict[str, Entity] = {}
        if entity_ids:
            stmt = select(Entity).where(Entity.entity_id.in_(entity_ids))
            rows = (await self.db.scalars(stmt)).all()
            entities = {e.entity_id: e for e in rows}

        candidates: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for anchor in anchor_signals:
            for target in target_signals:
                # Skip same-source comparisons
                anchor_tier = classify_source(anchor.source_name)
                target_tier = classify_source(target.source_name)
                if anchor.source_name == target.source_name:
                    continue
                if anchor_tier == target_tier:
                    continue

                pair_key = tuple(sorted([anchor.signal_id, target.signal_id]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                link = self._score_pair(anchor, target, entities)
                if link and link["score"] >= self.min_link_score:
                    candidates.append(link)
                    if len(candidates) >= max_candidates:
                        break
            if len(candidates) >= max_candidates:
                break

        candidates.sort(key=lambda x: x["score"], reverse=True)

        return {
            "links_found": len(candidates),
            "candidates": candidates,
            "anchor_count": len(anchor_signals),
            "target_count": len(target_signals),
            "time_window_days": int(self.time_window.days),
            "disclaimer": self.DISCLAIMER,
        }

    async def summary_stats(self) -> dict:
        """Return high-level cross-source coverage stats (no PII)."""
        cutoff = datetime.now(UTC) - self.time_window
        stmt = select(Signal).where(Signal.detected_at >= cutoff)
        signals = (await self.db.scalars(stmt)).all()

        by_tier: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for sig in signals:
            tier = classify_source(sig.source_name)
            by_tier[tier] = by_tier.get(tier, 0) + 1
            sn = sig.source_name or "unknown"
            by_source[sn] = by_source.get(sn, 0) + 1

        law_enforcement_count = by_tier.get("law_enforcement", 0)
        public_dataset_count = by_tier.get("public_dataset", 0)
        osint_count = by_tier.get("osint", 0)

        return {
            "total_signals_in_window": len(signals),
            "by_tier": by_tier,
            "sources": by_source,
            "cross_source_eligible": law_enforcement_count > 0 and (public_dataset_count + osint_count) > 0,
            "time_window_days": int(self.time_window.days),
        }

    def independent_corroboration(
        self,
        *,
        anchor_signals: list[Signal],
        candidate_signals: list[Signal],
        signal_to_case: dict[str, str],
        max_temporal_days: int = 45,
        max_candidates: int = 400,
    ) -> dict:
        """
        Collapse raw signal-link matches into independent corroboration metrics.

        Returns:
          {
            linked_cases,
            source_families,
            strong_matches,
            overlap_density,
            confidence,
            corroboration_tier,
            linked_case_ids,
            source_classes,
          }
        """
        if not anchor_signals or not candidate_signals:
            return {
                "linked_cases": 0,
                "source_families": 0,
                "strong_matches": 0,
                "overlap_density": 0.0,
                "confidence": 0.0,
                "corroboration_tier": "tier_0_single_source",
                "linked_case_ids": [],
                "source_classes": [],
            }

        max_seconds = max_temporal_days * 86400
        if len(candidate_signals) > max_candidates:
            candidate_signals = sorted(candidate_signals, key=lambda s: _to_utc(s.detected_at), reverse=True)[:max_candidates]

        # Precompute immutable features once to avoid expensive repeated work in nested loops.
        anchor_by_id = {a.signal_id for a in anchor_signals}
        anchor_features = []
        for anchor in anchor_signals:
            anchor_features.append(
                {
                    "signal_id": anchor.signal_id,
                    "dt": _to_utc(anchor.detected_at),
                    "geo": _extract_geo_tokens(
                        (anchor.evidence or "") + " " + (anchor.label or "") + " " + (anchor.raw_text_snippet or "")
                    ),
                    "signal_type": anchor.signal_type,
                    "source_class": classify_source_class(anchor.source_name),
                    "source_group": _normalize_source_group(anchor.source_name),
                }
            )

        candidate_features = []
        for candidate in candidate_signals:
            if candidate.signal_id in anchor_by_id:
                continue
            candidate_features.append(
                {
                    "signal_id": candidate.signal_id,
                    "dt": _to_utc(candidate.detected_at),
                    "geo": _extract_geo_tokens(
                        (candidate.evidence or "") + " " + (candidate.label or "") + " " + (candidate.raw_text_snippet or "")
                    ),
                    "signal_type": candidate.signal_type,
                    "source_class": classify_source_class(candidate.source_name),
                    "source_group": _normalize_source_group(candidate.source_name),
                }
            )

        linked_case_ids: set[str] = set()
        anchor_source_classes: set[str] = {str(a["source_class"]) for a in anchor_features if a.get("source_class")}
        candidate_source_classes: set[str] = set()
        source_groups: set[str] = {str(a.get("source_group") or "unknown") for a in anchor_features}
        strong_clusters: set[tuple[str, str, str]] = set()
        aligned_signal_types: set[str] = set()
        temporal_match_seconds: list[float] = []
        geo_token_frequency: dict[str, int] = {}
        examined = 0
        matched = 0

        for anchor in anchor_features:
            for candidate in candidate_features:
                candidate_class = candidate["source_class"]
                anchor_class = anchor["source_class"]
                if candidate_class == anchor_class:
                    continue

                examined += 1
                temporal_ok = abs((anchor["dt"] - candidate["dt"]).total_seconds()) <= max_seconds
                if not temporal_ok:
                    continue

                dt_seconds = abs((anchor["dt"] - candidate["dt"]).total_seconds())
                geo_overlap_tokens = anchor["geo"] & candidate["geo"]
                geo_overlap = bool(geo_overlap_tokens)
                type_overlap = anchor["signal_type"] == candidate["signal_type"]

                # Avoid over-linking on broad signal-type matches without geographic support.
                if not geo_overlap and type_overlap and str(anchor["signal_type"]) in _GENERIC_SIGNAL_TYPES:
                    continue

                # Type-only matches must be temporally tight to count as corroboration.
                if not (geo_overlap or (type_overlap and dt_seconds <= 7 * 86400)):
                    continue

                matched += 1
                candidate_source_classes.add(candidate_class)
                source_groups.add(str(candidate.get("source_group") or "unknown"))
                case_id = signal_to_case.get(candidate["signal_id"])
                if case_id:
                    linked_case_ids.add(case_id)

                temporal_match_seconds.append(dt_seconds)
                if type_overlap:
                    aligned_signal_types.add(str(anchor["signal_type"]))
                for token in geo_overlap_tokens:
                    geo_token_frequency[token] = geo_token_frequency.get(token, 0) + 1

                # Strong cluster: close in time and both geo+type corroborate.
                if dt_seconds <= 14 * 86400 and geo_overlap and type_overlap:
                    cluster_key = (
                        anchor["signal_type"],
                        candidate_class,
                        (sorted(geo_overlap_tokens) or ["n/a"])[0],
                    )
                    strong_clusters.add(cluster_key)

        overlap_density = round(min(1.0, matched / max(1, examined)), 3)
        linked_cases = len(linked_case_ids)
        source_classes = anchor_source_classes | candidate_source_classes
        source_families = len(source_classes)
        strong_matches = len(strong_clusters)
        confidence = round(
            min(
                0.99,
                0.25
                + min(0.35, linked_cases * 0.06)
                + min(0.25, source_families * 0.08)
                + min(0.10, strong_matches * 0.05)
                + min(0.04, overlap_density * 0.08),
            ),
            3,
        )

        # Corroboration tiers
        if source_families >= 3 and linked_cases >= 4 and strong_matches >= 1:
            tier = "tier_4_high_confidence_convergence"
        elif source_families >= 2 and linked_cases >= 3 and (strong_matches >= 1 or overlap_density >= 0.12):
            tier = "tier_3_multi_family_corroborated"
        elif source_families >= 2 and linked_cases >= 2 and (strong_matches >= 1 or overlap_density >= 0.06):
            tier = "tier_2_5_weak_multi_family_convergence"
        elif linked_cases >= 2:
            tier = "tier_2_multi_case_same_family"
        elif matched >= 2:
            tier = "tier_1_multi_signal_same_source"
        else:
            tier = "tier_0_single_source"

        top_geo_tokens = sorted(geo_token_frequency.items(), key=lambda kv: kv[1], reverse=True)
        display_geo_tokens = [token for token, _ in top_geo_tokens if len(token) > 2][:2]
        geo_overlap_summary = ", ".join(display_geo_tokens) if display_geo_tokens else "none"

        if temporal_match_seconds:
            min_days = round(min(temporal_match_seconds) / 86400, 2)
            max_days = round(max(temporal_match_seconds) / 86400, 2)
            if min_days == max_days:
                temporal_overlap_summary = f"within {min_days} days"
            else:
                temporal_overlap_summary = f"within {min_days}-{max_days} days"
        else:
            temporal_overlap_summary = "none"

        if not aligned_signal_types:
            aligned_signal_types.update({str(a.get("signal_type") or "") for a in anchor_features if a.get("signal_type")})

        convergence_explanation = {
            "source_families": sorted(source_groups),
            "geo_overlap": geo_overlap_summary,
            "temporal_overlap": temporal_overlap_summary,
            "signal_alignment": [s for s in sorted(aligned_signal_types)[:5] if s],
        }

        return {
            "linked_cases": linked_cases,
            "source_families": source_families,
            "strong_matches": strong_matches,
            "overlap_density": overlap_density,
            "confidence": confidence,
            "corroboration_tier": tier,
            "linked_case_ids": sorted(linked_case_ids),
            "source_classes": sorted(source_classes),
            "convergence_explanation": convergence_explanation,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_signals(
        self,
        cutoff: datetime,
        anchor_patterns: list[str] | None,
        target_patterns: list[str] | None,
    ) -> tuple[list[Signal], list[Signal]]:
        stmt = (
            select(Signal)
            .where(Signal.detected_at >= cutoff)
            .order_by(Signal.detected_at.desc())
            .limit(2000)
        )
        all_signals = (await self.db.scalars(stmt)).all()

        def matches(sig: Signal, patterns: list[str] | None) -> bool:
            if patterns is None:
                return True
            sn = (sig.source_name or "").lower()
            for pat in patterns:
                p = pat.lower()
                if p.endswith("*"):
                    if sn.startswith(p[:-1]):
                        return True
                else:
                    if sn == p or sn.startswith(p):
                        return True
            return False

        if anchor_patterns is None and target_patterns is None:
            # All-vs-all: any signal is anchor; compare against cross-tier signals
            return list(all_signals), list(all_signals)

        anchors = [s for s in all_signals if matches(s, anchor_patterns)]
        targets = [s for s in all_signals if matches(s, target_patterns)]
        return anchors, targets

    def _score_pair(
        self, anchor: Signal, target: Signal, entities: dict[str, Entity]
    ) -> dict | None:
        reasons: list[str] = []
        score = 0.0

        # --- Temporal proximity ---
        dt = abs((_to_utc(anchor.detected_at) - _to_utc(target.detected_at)).total_seconds())
        if dt < 86_400 * 7:      # within 7 days
            reasons.append("temporal_proximity_7d")
            score += 0.30
        elif dt < 86_400 * 30:   # within 30 days
            reasons.append("temporal_proximity_30d")
            score += 0.15

        # --- Geographic overlap ---
        anchor_geo = _extract_geo_tokens(
            (anchor.evidence or "") + " " + (anchor.label or "") + " " + (anchor.raw_text_snippet or "")
        )
        target_geo = _extract_geo_tokens(
            (target.evidence or "") + " " + (target.label or "") + " " + (target.raw_text_snippet or "")
        )
        shared_geo = anchor_geo & target_geo
        if len(shared_geo) >= self.geo_min_overlap:
            reasons.append(f"shared_location:{','.join(sorted(shared_geo)[:3])}")
            score += 0.20 * min(len(shared_geo), 3)

        # --- Name token overlap ---
        anchor_entity = entities.get(anchor.entity_id or "")
        target_entity = entities.get(target.entity_id or "")
        if anchor_entity and target_entity and anchor_entity.entity_id != target_entity.entity_id:
            a_tokens = _name_tokens(anchor_entity.canonical_name)
            t_tokens = _name_tokens(target_entity.canonical_name)
            shared_names = a_tokens & t_tokens
            if len(shared_names) >= self.name_min_overlap:
                reasons.append(f"shared_name_token:{','.join(sorted(shared_names)[:2])}")
                score += 0.35 * min(len(shared_names), 2)

        # --- Same signal type across sources (corroboration) ---
        if anchor.signal_type == target.signal_type:
            reasons.append(f"corroborating_signal_type:{anchor.signal_type}")
            score += 0.15

        if not reasons:
            return None

        score = round(min(score, 1.0), 3)
        anchor_tier = classify_source(anchor.source_name)
        target_tier = classify_source(target.source_name)

        # Boost score if one side is law enforcement (higher authority corroboration)
        if "law_enforcement" in (anchor_tier, target_tier):
            score = round(min(score * 1.25, 1.0), 3)

        return {
            "score": score,
            "link_reasons": reasons,
            "anchor": {
                "signal_id": anchor.signal_id,
                "source_name": anchor.source_name,
                "source_tier": anchor_tier,
                "signal_type": anchor.signal_type,
                "label": anchor.label,
                "entity_id": anchor.entity_id,
                "entity_name": anchor_entity.canonical_name if anchor_entity else None,
            },
            "target": {
                "signal_id": target.signal_id,
                "source_name": target.source_name,
                "source_tier": target_tier,
                "signal_type": target.signal_type,
                "label": target.label,
                "entity_id": target.entity_id,
                "entity_name": target_entity.canonical_name if target_entity else None,
            },
            "disclaimer": self.DISCLAIMER,
        }
