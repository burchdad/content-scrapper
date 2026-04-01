"""Source tier classification for authority weighting and badge display.

Every ingested signal carries a source_name. This module maps those names
to one of three tiers and returns badge metadata used by the risk scorer,
explainability service, and dashboard UI.

Tiers
-----
law_enforcement  – FBI, Interpol (highest authority, confidence boost)
public_dataset   – NamUs, NCMEC, CourtListener (official public registries/records)
osint            – NewsAPI, social media, unclassified web sources
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

_SOURCE_TIER_MAP: list[tuple[str, str]] = [
    # (prefix_or_exact, tier)  — checked in order; first match wins
    ("fbi most wanted", "law_enforcement"),
    ("fbi_wanted", "law_enforcement"),
    ("fbi-", "law_enforcement"),
    ("interpol", "law_enforcement"),
    ("law_enforcement", "law_enforcement"),
    # ---- public datasets ----
    ("namus", "public_dataset"),
    ("ncmec", "public_dataset"),
    ("courtlistener", "public_dataset"),
    ("court_", "public_dataset"),
    # ---- OSINT ----
    ("newsapi", "osint"),
    ("newsapi-", "osint"),
    ("gdelt", "osint"),
    ("polaris_project", "osint"),
    ("polaris", "osint"),
    ("social_media", "osint"),
    ("twitter", "osint"),
    ("x_platform", "osint"),
]

_SOURCE_CLASS_MAP: list[tuple[str, str]] = [
    ("fbi most wanted", "law_enforcement_direct"),
    ("fbi_wanted", "law_enforcement_direct"),
    ("fbi-", "law_enforcement_direct"),
    ("interpol", "law_enforcement_direct"),
    ("namus", "reference_registry"),
    ("ncmec", "reference_registry"),
    ("courtlistener", "legal_public_record"),
    ("court_", "legal_public_record"),
    ("newsapi", "osint_news_social"),
    ("newsapi-", "osint_news_social"),
    ("gdelt", "osint_news_social"),
    ("polaris_project", "osint_news_social"),
    ("polaris", "osint_news_social"),
    ("social_media", "osint_news_social"),
    ("twitter", "osint_news_social"),
    ("x_platform", "osint_news_social"),
    ("synth", "synthetic_test"),
]

_TIER_METADATA: dict[str, dict] = {
    "law_enforcement": {
        "label": "Law Enforcement",
        "short": "LE",
        "css_class": "badge-law-enforcement",
        "color": "#3b82f6",   # blue
        "confidence_boost": 0.15,   # added to signal confidence
        "risk_boost": 12.0,          # added to raw risk score
        "framing": (
            "This case includes law enforcement–sourced data, which increases "
            "confidence weighting. Data appears in publicly available law "
            "enforcement records and is analyzed alongside other signals."
        ),
        "guardrail": (
            "Appearance in law enforcement records does not imply guilt. "
            "Human review is required before any enforcement or referral action."
        ),
    },
    "public_dataset": {
        "label": "Public Dataset",
        "short": "PD",
        "css_class": "badge-public-dataset",
        "color": "#f59e0b",   # amber
        "confidence_boost": 0.05,
        "risk_boost": 4.0,
        "framing": (
            "This case draws on official public records (government or court data), "
            "providing stronger evidentiary grounding than unverified OSINT signals."
        ),
        "guardrail": (
            "Public record inclusion reflects documented filing or registry status "
            "only — not a determination of guilt or harm."
        ),
    },
    "osint": {
        "label": "OSINT Signal",
        "short": "OSINT",
        "css_class": "badge-osint",
        "color": "#10b981",   # emerald
        "confidence_boost": 0.0,
        "risk_boost": 0.0,
        "framing": (
            "This case is based on open-source intelligence signals. "
            "OSINT signals require additional corroboration before escalation."
        ),
        "guardrail": (
            "OSINT data may contain errors, satire, or misinformation. "
            "Cross-reference with authoritative sources before acting."
        ),
    },
}

_UNKNOWN_TIER = {
    "label": "Unknown Source",
    "short": "?",
    "css_class": "badge-unknown",
    "color": "#64748b",
    "confidence_boost": 0.0,
    "risk_boost": 0.0,
    "framing": "Source classification unavailable.",
    "guardrail": "Human review required.",
}

_SOURCE_CLASS_METADATA: dict[str, dict] = {
    "law_enforcement_direct": {
        "label": "Law Enforcement Direct",
        "risk_cap": 95.0,
        "confidence_cap": 0.92,
    },
    "reference_registry": {
        "label": "Reference Victim Registry",
        "risk_cap": 70.0,
        "confidence_cap": 0.75,
    },
    "legal_public_record": {
        "label": "Legal/Public Record",
        "risk_cap": 60.0,
        "confidence_cap": 0.72,
    },
    "osint_news_social": {
        "label": "OSINT / News / Social",
        "risk_cap": 65.0,
        "confidence_cap": 0.70,
    },
    "synthetic_test": {
        "label": "Synthetic / Test",
        "risk_cap": 25.0,
        "confidence_cap": 0.40,
    },
}

_UNKNOWN_SOURCE_CLASS = {
    "label": "Unknown Source Class",
    "risk_cap": 65.0,
    "confidence_cap": 0.70,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_source(source_name: str | None) -> str:
    """Return the tier name for a given source_name string."""
    if not source_name:
        return "osint"
    norm = source_name.strip().lower()
    for prefix, tier in _SOURCE_TIER_MAP:
        if norm.startswith(prefix) or norm == prefix:
            return tier
    return "osint"


def get_tier_meta(source_name: str | None) -> dict:
    """Return full badge/boost metadata dict for a source_name."""
    tier = classify_source(source_name)
    return {"tier": tier, **_TIER_METADATA.get(tier, _UNKNOWN_TIER)}


def classify_source_class(source_name: str | None) -> str:
    """Return the source calibration class for a source_name string."""
    if not source_name:
        return "osint_news_social"
    norm = source_name.strip().lower()
    for prefix, source_class in _SOURCE_CLASS_MAP:
        if norm.startswith(prefix) or norm == prefix:
            return source_class
    return "osint_news_social"


def get_source_class_meta(source_name: str | None) -> dict:
    """Return calibration class metadata for a source_name."""
    source_class = classify_source_class(source_name)
    return {"source_class": source_class, **_SOURCE_CLASS_METADATA.get(source_class, _UNKNOWN_SOURCE_CLASS)}


def source_classes_present(source_names: list[str | None]) -> list[str]:
    """Return sorted unique list of calibration classes present across source_names."""
    return sorted({classify_source_class(s) for s in source_names if s})


def authority_boost_for_sources(source_names: list[str | None]) -> float:
    """
    Given a list of signal source_names, return the highest applicable
    risk_boost across all sources (boosts do not stack — take the max).
    """
    if not source_names:
        return 0.0
    max_boost = max(
        _TIER_METADATA.get(classify_source(s), _UNKNOWN_TIER)["risk_boost"]
        for s in source_names
    )
    return max_boost


def confidence_boost_for_sources(source_names: list[str | None]) -> float:
    """Return max confidence_boost across all source_names."""
    if not source_names:
        return 0.0
    return max(
        _TIER_METADATA.get(classify_source(s), _UNKNOWN_TIER)["confidence_boost"]
        for s in source_names
    )


def tiers_present(source_names: list[str | None]) -> list[str]:
    """Return sorted unique list of tiers present across source_names."""
    return sorted({classify_source(s) for s in source_names if s})


def source_impact_summary(source_names: list[str | None]) -> dict:
    """
    Build the full source_impact block used by the explainability service.

    Returns:
        {
          "tiers": ["law_enforcement", ...],
          "highest_tier": "law_enforcement",
          "risk_boost_applied": 12.0,
          "confidence_boost_applied": 0.15,
          "badges": [{"tier", "label", "short", "css_class", "color"}, ...],
          "framing": "...",
          "guardrail": "...",
        }
    """
    if not source_names:
        return {
            "tiers": [],
            "source_classes": [],
            "highest_tier": None,
            "risk_boost_applied": 0.0,
            "confidence_boost_applied": 0.0,
            "badges": [],
            "framing": "No source classification available.",
            "guardrail": "Human review required.",
        }

    tiers = tiers_present(source_names)
    source_classes = source_classes_present(source_names)
    _tier_order = ["law_enforcement", "public_dataset", "osint"]
    highest_tier = next((t for t in _tier_order if t in tiers), tiers[0] if tiers else None)

    badges = []
    seen_tiers: set[str] = set()
    for s in source_names:
        tier = classify_source(s)
        if tier not in seen_tiers:
            seen_tiers.add(tier)
            meta = _TIER_METADATA.get(tier, _UNKNOWN_TIER)
            badges.append({
                "tier": tier,
                "label": meta["label"],
                "short": meta["short"],
                "css_class": meta["css_class"],
                "color": meta["color"],
            })

    highest_meta = _TIER_METADATA.get(highest_tier, _UNKNOWN_TIER) if highest_tier else _UNKNOWN_TIER
    return {
        "tiers": tiers,
        "source_classes": source_classes,
        "highest_tier": highest_tier,
        "risk_boost_applied": authority_boost_for_sources(source_names),
        "confidence_boost_applied": confidence_boost_for_sources(source_names),
        "badges": badges,
        "framing": highest_meta["framing"],
        "guardrail": highest_meta["guardrail"],
    }
