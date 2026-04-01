from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.case import Case
from app.models.signal import Signal
from app.services.case_priority_service import CasePriorityService
from app.services.explainability_service import ExplainabilityService
from app.models.feedback import AnalystFeedback
from app.services.feedback_service import decision_weight_for_notes, parse_decision_role, parse_decision_type


router = APIRouter(prefix="/api/v1/system", tags=["system"])

QUALITY_TARGETS = {
    "avg_source_families": {"min": 2.0, "max": 3.5},
    "avg_linked_cases": {"min": 3.0, "max": 8.0},
    "avg_confidence": {"min": 0.65, "max": 0.85},
    "tier_3_plus_ratio": {"min": 0.15, "max": 0.35},
}


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


async def _source_contribution_panel(db: AsyncSession) -> dict:
    recent_cutoff = datetime.now(UTC) - timedelta(days=60)

    signal_rows = (
        await db.scalars(
            select(Signal)
            .where(Signal.detected_at >= recent_cutoff)
            .order_by(desc(Signal.detected_at))
            .limit(6000)
        )
    ).all()

    case_rows = (
        await db.scalars(
            select(Case)
            .where(Case.updated_at >= recent_cutoff)
            .order_by(desc(Case.updated_at))
            .limit(1200)
        )
    ).all()

    source_stats: dict[str, dict[str, float | int]] = {}
    signal_to_group: dict[str, str] = {}

    for signal in signal_rows:
        group = _normalize_source_group(signal.source_name)
        signal_to_group[signal.signal_id] = group
        bucket = source_stats.setdefault(
            group,
            {
                "signals": 0,
                "linked_cases": 0,
                "tier_2_5_contributions": 0,
                "tier_3_contributions": 0,
                "tier_4_contributions": 0,
                "avg_confidence": 0.0,
                "_confidence_sum": 0.0,
            },
        )
        bucket["signals"] = int(bucket["signals"]) + 1
        bucket["_confidence_sum"] = float(bucket["_confidence_sum"]) + float(signal.confidence or 0.0)

    for group, bucket in source_stats.items():
        signals = max(1, int(bucket["signals"]))
        bucket["avg_confidence"] = round(float(bucket["_confidence_sum"]) / signals, 3)
        bucket.pop("_confidence_sum", None)

    # linked_cases: source participates in case if any signal in case belongs to that source group.
    for case in case_rows:
        groups_in_case: set[str] = set()
        for signal_id in case.signal_ids or []:
            group = signal_to_group.get(signal_id)
            if group:
                groups_in_case.add(group)
        for group in groups_in_case:
            if group in source_stats:
                source_stats[group]["linked_cases"] = int(source_stats[group]["linked_cases"]) + 1

    # tier contributions: use priority service's corroboration tier over recent case slice.
    if case_rows:
        scoring_slice = case_rows[:300]
        scored = await CasePriorityService(db).score_cases(scoring_slice, apply_saturation=True)
        for case in scoring_slice:
            data = scored.get(case.case_id) or {}
            tier = str(data.get("corroboration_tier") or "")
            if tier not in {
                "tier_2_5_weak_multi_family_convergence",
                "tier_3_multi_family_corroborated",
                "tier_4_high_confidence_convergence",
            }:
                continue
            groups_in_case: set[str] = set()
            for signal_id in case.signal_ids or []:
                group = signal_to_group.get(signal_id)
                if group:
                    groups_in_case.add(group)
            for group in groups_in_case:
                if group not in source_stats:
                    continue
                if tier == "tier_2_5_weak_multi_family_convergence":
                    source_stats[group]["tier_2_5_contributions"] = int(source_stats[group]["tier_2_5_contributions"]) + 1
                if tier == "tier_3_multi_family_corroborated":
                    source_stats[group]["tier_3_contributions"] = int(source_stats[group]["tier_3_contributions"]) + 1
                if tier == "tier_4_high_confidence_convergence":
                    source_stats[group]["tier_4_contributions"] = int(source_stats[group]["tier_4_contributions"]) + 1

    # keep deterministic ordering and hide empty buckets unless signal volume exists
    ordered = ["gdelt", "polaris", "newsapi", "interpol", "fbi", "namus", "ncmec", "courtlistener", "other", "unknown"]
    out: dict[str, dict] = {}
    for key in ordered:
        bucket = source_stats.get(key)
        if not bucket:
            out[key] = {
                "signals": 0,
                "linked_cases": 0,
                "tier_2_5_contributions": 0,
                "tier_3_contributions": 0,
                "tier_4_contributions": 0,
                "avg_confidence": 0.0,
                "link_efficiency": 0.0,
                "tier_2_5_rate": 0.0,
                "tier_3_rate": 0.0,
                "tier_4_rate": 0.0,
            }
            continue
        signals = int(bucket["signals"])
        linked_cases = int(bucket["linked_cases"])
        tier_2_5_contributions = int(bucket["tier_2_5_contributions"])
        tier_3_contributions = int(bucket["tier_3_contributions"])
        tier_4_contributions = int(bucket["tier_4_contributions"])
        out[key] = {
            "signals": signals,
            "linked_cases": linked_cases,
            "tier_2_5_contributions": tier_2_5_contributions,
            "tier_3_contributions": tier_3_contributions,
            "tier_4_contributions": tier_4_contributions,
            "avg_confidence": float(bucket["avg_confidence"]),
            "link_efficiency": round(linked_cases / max(1, signals), 3),
            "tier_2_5_rate": round(tier_2_5_contributions / max(1, linked_cases), 3),
            "tier_3_rate": round(tier_3_contributions / max(1, linked_cases), 3),
            "tier_4_rate": round(tier_4_contributions / max(1, linked_cases), 3),
        }
    return out


async def _fallback_quality_from_recent_cases(db: AsyncSession) -> dict:
    cases = (
        await db.scalars(
            select(Case)
            .order_by(desc(Case.updated_at))
            .limit(160)
        )
    ).all()

    tier_distribution = {
        "tier_0_single_source": 0,
        "tier_1_multi_signal_same_source": 0,
        "tier_2_multi_case_same_family": 0,
        "tier_2_5_weak_multi_family_convergence": 0,
        "tier_3_multi_family_corroborated": 0,
        "tier_4_high_confidence_convergence": 0,
        "unknown": 0,
    }

    if not cases:
        return {
            "samples": 0,
            "avg_source_families": 0.0,
            "avg_linked_cases": 0.0,
            "avg_confidence": 0.0,
            "tier_distribution": tier_distribution,
            "source": "recent_cases_fallback",
        }

    scored = await CasePriorityService(db).score_cases(cases, apply_saturation=True)

    samples = 0
    source_family_total = 0
    linked_cases_total = 0
    confidence_total = 0.0

    for case in cases:
        data = scored.get(case.case_id) or {}
        corr = data.get("independent_corroboration") or {}
        if not corr:
            continue
        samples += 1
        source_family_total += int(corr.get("source_families") or 0)
        linked_cases_total += int(corr.get("linked_cases") or 0)
        confidence_total += float(corr.get("confidence") or 0.0)
        tier = str(corr.get("corroboration_tier") or "unknown")
        if tier not in tier_distribution:
            tier = "unknown"
        tier_distribution[tier] += 1

    if samples == 0:
        return {
            "samples": 0,
            "avg_source_families": 0.0,
            "avg_linked_cases": 0.0,
            "avg_confidence": 0.0,
            "tier_distribution": tier_distribution,
            "source": "recent_cases_fallback",
        }

    return {
        "samples": samples,
        "avg_source_families": round(source_family_total / samples, 3),
        "avg_linked_cases": round(linked_cases_total / samples, 3),
        "avg_confidence": round(confidence_total / samples, 3),
        "tier_distribution": tier_distribution,
        "source": "recent_cases_fallback",
    }


def _range_score(value: float, low: float, high: float, *, tolerance: float) -> float:
    if low <= value <= high:
        return 1.0
    if value < low:
        delta = low - value
    else:
        delta = value - high
    return max(0.0, 1.0 - (delta / max(tolerance, 1e-6)))


def _build_quality_alerts(cache: dict, quality: dict) -> list[str]:
    alerts: list[str] = []
    samples = int(quality.get("samples") or 0)
    if samples == 0:
        alerts.append("NO_CORROBORATION_SAMPLES")
        return alerts

    avg_source_families = float(quality.get("avg_source_families") or 0.0)
    avg_linked_cases = float(quality.get("avg_linked_cases") or 0.0)
    avg_confidence = float(quality.get("avg_confidence") or 0.0)
    tier_distribution = quality.get("tier_distribution") or {}

    tier0 = int(tier_distribution.get("tier_0_single_source") or 0)
    tier3 = int(tier_distribution.get("tier_3_multi_family_corroborated") or 0)
    tier4 = int(tier_distribution.get("tier_4_high_confidence_convergence") or 0)
    tier0_ratio = tier0 / max(1, samples)
    tier3_plus_ratio = (tier3 + tier4) / max(1, samples)

    if avg_source_families < QUALITY_TARGETS["avg_source_families"]["min"]:
        alerts.append("LOW_CROSS_SOURCE_DIVERSITY")
    if avg_linked_cases < QUALITY_TARGETS["avg_linked_cases"]["min"]:
        alerts.append("LOW_CORROBORATION_DENSITY")
    if avg_confidence > QUALITY_TARGETS["avg_confidence"]["max"]:
        alerts.append("CONFIDENCE_SKEW_HIGH")
    if avg_confidence < QUALITY_TARGETS["avg_confidence"]["min"]:
        alerts.append("CONFIDENCE_SKEW_LOW")
    if tier0_ratio > 0.60:
        alerts.append("HIGH_TIER_0_RATIO")
    if tier3_plus_ratio < QUALITY_TARGETS["tier_3_plus_ratio"]["min"]:
        alerts.append("LOW_HIGH_CONFIDENCE_CONVERGENCE")

    hit_rate = float(cache.get("hit_rate") or 0.0)
    if hit_rate < 0.50:
        alerts.append("LOW_CACHE_HIT_RATE")

    return alerts


def _system_health(cache: dict, quality: dict, alerts: list[str]) -> dict:
    hit_rate = float(cache.get("hit_rate") or 0.0)
    avg_compute_ms = float(cache.get("avg_compute_ms") or 0.0)

    quality_samples = int(quality.get("samples") or 0)
    avg_source_families = float(quality.get("avg_source_families") or 0.0)
    avg_linked_cases = float(quality.get("avg_linked_cases") or 0.0)
    avg_confidence = float(quality.get("avg_confidence") or 0.0)
    tier_distribution = quality.get("tier_distribution") or {}
    tier3_plus_ratio = (
        float(tier_distribution.get("tier_3_multi_family_corroborated") or 0)
        + float(tier_distribution.get("tier_4_high_confidence_convergence") or 0)
    ) / max(1.0, float(quality_samples))

    performance_score = (
        0.6 * min(1.0, max(0.0, hit_rate))
        + 0.4 * _range_score(avg_compute_ms, 0.0, 120.0, tolerance=160.0)
    )

    quality_score = (
        0.25 * _range_score(avg_source_families, 2.0, 3.5, tolerance=2.0)
        + 0.25 * _range_score(avg_linked_cases, 3.0, 8.0, tolerance=5.0)
        + 0.30 * _range_score(avg_confidence, 0.65, 0.85, tolerance=0.35)
        + 0.20 * _range_score(tier3_plus_ratio, 0.15, 0.35, tolerance=0.35)
    )

    evictions = int(cache.get("evictions") or 0)
    prunes = int(cache.get("prunes") or 0)
    pressure = evictions + prunes
    stability_score = max(0.0, 1.0 - min(1.0, pressure / 500.0) - min(0.5, len(alerts) * 0.05))

    if quality_samples == 0:
        quality_score = 0.0
        stability_score = min(stability_score, 0.5)

    overall_score = 0.40 * performance_score + 0.40 * quality_score + 0.20 * stability_score

    return {
        "performance": round(performance_score, 3),
        "corroboration_quality": round(quality_score, 3),
        "stability": round(stability_score, 3),
        "overall": round(overall_score, 3),
    }


async def _tier4_proof_artifact(db: AsyncSession) -> dict:
    recent_cases = (
        await db.scalars(select(Case).order_by(desc(Case.updated_at)).limit(500))
    ).all()
    if not recent_cases:
        return {"found": False, "reason": "no_cases_available"}

    scored = await CasePriorityService(db).score_cases(recent_cases, apply_saturation=True)
    tier4 = [
        (case, scored.get(case.case_id) or {})
        for case in recent_cases
        if (scored.get(case.case_id) or {}).get("corroboration_tier") == "tier_4_high_confidence_convergence"
    ]
    if not tier4:
        tier3_count = sum(
            1 for case in recent_cases
            if (scored.get(case.case_id) or {}).get("corroboration_tier") == "tier_3_multi_family_corroborated"
        )
        return {
            "found": False,
            "reason": "tier4_not_yet_observed",
            "tier3_ready_count": tier3_count,
        }

    tier4.sort(key=lambda item: float((item[1] or {}).get("priority_score") or 0.0), reverse=True)
    case, data = tier4[0]
    corroboration = data.get("independent_corroboration") or {}
    convergence = corroboration.get("convergence_explanation") or {}

    feedback_rows = (
        await db.scalars(
            select(AnalystFeedback)
            .where(AnalystFeedback.case_id == case.case_id)
            .order_by(desc(AnalystFeedback.created_at))
            .limit(200)
        )
    ).all()

    decision_counts: dict[str, int] = {}
    decisions_by_role: dict[str, int] = {
        "junior_analyst": 0,
        "senior_analyst": 0,
        "trusted_operator": 0,
    }
    for row in feedback_rows:
        decision = parse_decision_type(row.notes)
        if decision:
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        role = parse_decision_role(row.notes)
        if role in decisions_by_role:
            decisions_by_role[role] += 1

    return {
        "found": True,
        "case_id": case.case_id,
        "priority_score": data.get("priority_score"),
        "risk_score": case.risk_score,
        "priority_band": data.get("priority_band"),
        "corroboration_tier": data.get("corroboration_tier"),
        "convergence_explanation": convergence,
        "independent_corroboration": {
            "source_families": corroboration.get("source_families"),
            "linked_cases": corroboration.get("linked_cases"),
            "strong_matches": corroboration.get("strong_matches"),
            "confidence": corroboration.get("confidence"),
            "linked_case_ids": corroboration.get("linked_case_ids") or [],
            "source_classes": corroboration.get("source_classes") or [],
        },
        "governance": {
            "analyst_decision_counts": decision_counts,
            "decisions_by_role": decisions_by_role,
            "feedback_count": len(feedback_rows),
        },
        "captured_at": datetime.now(UTC).isoformat(),
    }


def _render_tier4_pdf(case: Case, proof: dict, explainability: dict, signals: list[Signal], feedback_rows: list[AnalystFeedback]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"PDF generator unavailable: {exc}") from exc

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=f"GhostRescue Tier 4 Proof - {case.case_id}")
    styles = getSampleStyleSheet()
    story: list = []

    priority = proof.get("priority_score")
    risk = proof.get("risk_score")
    convergence = proof.get("convergence_explanation") or {}
    corr = proof.get("independent_corroboration") or {}
    feedback_summary = explainability.get("feedback_summary") or {}

    story.append(Paragraph("GhostRescue Tier 4 Proof Report", styles["Title"]))
    story.append(Paragraph(f"Case: <b>{case.case_id}</b>", styles["Heading2"]))
    story.append(Paragraph(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Executive Summary", styles["Heading2"]))
    summary_text = (
        f"This report documents a validated <b>Tier 4 high-confidence convergence</b> case. "
        f"The case reached urgent priority with score <b>{priority}</b> (risk {risk}) based on "
        f"independent corroboration across source classes: {', '.join(corr.get('source_classes') or []) or 'n/a'}."
    )
    story.append(Paragraph(summary_text, styles["BodyText"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("How It Was Located", styles["Heading3"]))
    story.append(Paragraph(
        "The case was identified through GhostRescue's cross-source priority engine, which separates risk from priority and promotes multi-family corroboration. "
        "Tier 4 was triggered when independent source-family convergence and strong temporal/signal alignment thresholds were met.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("How It Was Confirmed", styles["Heading3"]))
    conv_rows = [
        ["Corroboration Tier", proof.get("corroboration_tier") or "n/a"],
        ["Source Families", str(corr.get("source_families") or 0)],
        ["Linked Cases", str(corr.get("linked_cases") or 0)],
        ["Strong Matches", str(corr.get("strong_matches") or 0)],
        ["Convergence Confidence", str(corr.get("confidence") or 0.0)],
        ["Geo Overlap", convergence.get("geo_overlap") or "none"],
        ["Temporal Overlap", convergence.get("temporal_overlap") or "none"],
        ["Signal Alignment", ", ".join(convergence.get("signal_alignment") or []) or "none"],
    ]
    conv_table = Table(conv_rows, colWidths=[170, 360])
    conv_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(conv_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Source Breakdown", styles["Heading3"]))
    source_counts: dict[str, int] = {}
    for s in signals:
        key = s.source_name or "unknown"
        source_counts[key] = source_counts.get(key, 0) + 1
    src_rows = [["Source", "Signals"]] + [[k, str(v)] for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)]
    src_table = Table(src_rows, colWidths=[400, 130])
    src_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(src_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Signal Timeline", styles["Heading3"]))
    timeline = sorted(signals, key=lambda s: s.detected_at)
    tl_rows = [["Detected", "Source", "Signal Type", "Confidence"]]
    for s in timeline[:25]:
        ts = s.detected_at.isoformat() if s.detected_at else "n/a"
        tl_rows.append([ts[:19].replace("T", " "), s.source_name or "unknown", s.signal_type, f"{float(s.confidence or 0.0):.2f}"])
    tl_table = Table(tl_rows, colWidths=[120, 190, 145, 75])
    tl_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tl_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Analyst Decision Log", styles["Heading3"]))
    dec_rows = [["When", "Analyst", "Role", "Decision", "Weight"]]
    for fb in feedback_rows[:20]:
        dec = parse_decision_type(fb.notes) or "unlabeled"
        role = parse_decision_role(fb.notes)
        weight = decision_weight_for_notes(fb.notes)
        when = fb.created_at.isoformat()[:19].replace("T", " ") if fb.created_at else "n/a"
        dec_rows.append([when, fb.analyst_id, role, dec, f"{weight:.1f}"])
    if len(dec_rows) == 1:
        dec_rows.append(["n/a", "n/a", "n/a", "No analyst decisions recorded", "-"])
    dec_table = Table(dec_rows, colWidths=[105, 120, 110, 170, 25])
    dec_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(dec_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Operational Usefulness for Field Office Review", styles["Heading3"]))
    op_text = (
        "This Tier 4 case is operationally useful because it is independently corroborated across multiple source families, "
        "has high convergence confidence, and includes full auditability (priority rationale, analyst actions, and role-weighted influence). "
        "Recommended actions: 1) review linked cases for jurisdiction overlap, 2) validate top aligned signals, 3) apply local investigative context before escalation."
    )
    story.append(Paragraph(op_text, styles["BodyText"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Feedback summary: {feedback_summary.get('feedback_count', 0)} entries, "
        f"false positive rate {feedback_summary.get('false_positive_rate', 0.0)}.",
        styles["Normal"],
    ))

    doc.build(story)
    return buf.getvalue()


async def _resolve_tier4_case_and_proof(db: AsyncSession, case_id: str | None = None) -> tuple[Case, dict]:
    proof = await _tier4_proof_artifact(db)
    if case_id:
        case = await db.scalar(select(Case).where(Case.case_id == case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        if not proof.get("found") or proof.get("case_id") != case_id:
            # Build from explicit case if caller requests it; requires case to currently score Tier 4.
            scored = await CasePriorityService(db).score_case(case)
            if scored.get("corroboration_tier") != "tier_4_high_confidence_convergence":
                raise HTTPException(status_code=400, detail="Requested case is not currently Tier 4")
            proof = {
                "found": True,
                "case_id": case.case_id,
                "priority_score": scored.get("priority_score"),
                "risk_score": case.risk_score,
                "priority_band": scored.get("priority_band"),
                "corroboration_tier": scored.get("corroboration_tier"),
                "convergence_explanation": (scored.get("independent_corroboration") or {}).get("convergence_explanation") or {},
                "independent_corroboration": scored.get("independent_corroboration") or {},
            }
        return case, proof

    if not proof.get("found"):
        raise HTTPException(status_code=404, detail="No Tier 4 proof case currently available")
    case = await db.scalar(select(Case).where(Case.case_id == proof["case_id"]))
    if not case:
        raise HTTPException(status_code=404, detail="Tier 4 case not found")
    return case, proof


def _safe_case_id(case_id: str) -> str:
    safe = []
    for ch in case_id:
        if ch.isalnum() or ch in {"-", "_"}:
            safe.append(ch)
        else:
            safe.append("-")
    return "".join(safe)


def _archive_root_path() -> Path:
    settings = get_settings()
    root = Path(settings.tier4_archive_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else {}
    except Exception:
        return {}


def _write_json_file(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _derive_integrity_hash_from_files(pdf_path: str | None, json_path: str | None) -> str | None:
    if not pdf_path or not json_path:
        return None
    try:
        pdf_bytes = Path(pdf_path).read_bytes()
        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        payload_no_hash = dict(payload)
        payload_no_hash.pop("integrity_hash", None)
        artifact_bytes = json.dumps(payload_no_hash, sort_keys=True).encode("utf-8")
        return hashlib.sha256(pdf_bytes + artifact_bytes).hexdigest()
    except Exception:
        return None


async def _tier4_report_materials(db: AsyncSession, case: Case, proof: dict) -> tuple[bytes, list[Signal], list[AnalystFeedback], dict]:
    signals = (
        await db.scalars(select(Signal).where(Signal.signal_id.in_(case.signal_ids or [])))
    ).all()
    feedback_rows = (
        await db.scalars(
            select(AnalystFeedback)
            .where(AnalystFeedback.case_id == case.case_id)
            .order_by(desc(AnalystFeedback.created_at))
            .limit(200)
        )
    ).all()
    explainability = await ExplainabilityService(db).case_explainability(case.case_id)
    pdf_bytes = _render_tier4_pdf(case, proof, explainability, signals, feedback_rows)
    return pdf_bytes, signals, feedback_rows, explainability


async def _archive_tier4_case(db: AsyncSession, case: Case, proof: dict) -> dict:
    root = _archive_root_path()
    root.mkdir(parents=True, exist_ok=True)

    index_path = root / "archive_index.json"
    index = _read_json_file(index_path)
    existing = index.get(case.case_id)
    if isinstance(existing, dict):
        integrity_hash = existing.get("integrity_hash")
        if not integrity_hash:
            integrity_hash = _derive_integrity_hash_from_files(existing.get("pdf_path"), existing.get("json_path"))
        return {
            "status": "already_archived",
            "case_id": case.case_id,
            "date": existing.get("date"),
            "pdf_path": existing.get("pdf_path"),
            "json_path": existing.get("json_path"),
            "metadata_path": existing.get("metadata_path"),
            "archived_at": existing.get("archived_at"),
            "integrity_hash": integrity_hash,
            "webhook": {"status": "skipped", "reason": "already_archived"},
        }

    pdf_bytes, _, _, _ = await _tier4_report_materials(db, case, proof)

    now = datetime.now(UTC)
    date_key = now.strftime("%Y-%m-%d")
    case_safe = _safe_case_id(case.case_id)
    day_dir = root / date_key
    day_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = day_dir / f"{case_safe}.pdf"
    json_path = day_dir / f"{case_safe}.json"
    metadata_path = day_dir / "metadata.json"

    pdf_path.write_bytes(pdf_bytes)
    artifact = {
        "case_id": case.case_id,
        "archived_at": now.isoformat(),
        "proof": proof,
    }
    corr = proof.get("independent_corroboration") or {}
    artifact_bytes = json.dumps(artifact, sort_keys=True).encode("utf-8")
    integrity_hash = hashlib.sha256(pdf_bytes + artifact_bytes).hexdigest()
    artifact["integrity_hash"] = integrity_hash
    _write_json_file(json_path, artifact)

    daily_metadata = _read_json_file(metadata_path)
    cases = daily_metadata.get("cases")
    if not isinstance(cases, list):
        cases = []

    cases.append(
        {
            "case_id": case.case_id,
            "priority": proof.get("priority_score"),
            "confidence": corr.get("confidence"),
            "timestamp": now.isoformat(),
            "source_families": corr.get("source_families"),
            "integrity_hash": integrity_hash,
        }
    )
    _write_json_file(
        metadata_path,
        {
            "date": date_key,
            "cases": cases,
        },
    )

    index[case.case_id] = {
        "case_id": case.case_id,
        "date": date_key,
        "archived_at": now.isoformat(),
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "metadata_path": str(metadata_path),
        "integrity_hash": integrity_hash,
    }
    _write_json_file(index_path, index)

    webhook_result = _send_archive_webhook(
        {
            "event": "tier4_case_detected",
            "case_id": case.case_id,
            "priority": proof.get("priority_score"),
            "confidence": corr.get("confidence"),
            "timestamp": now.isoformat(),
            "source_families": corr.get("source_families"),
            "integrity_hash": integrity_hash,
            "archive_date": date_key,
            "pdf_path": str(pdf_path),
            "json_path": str(json_path),
        }
    )

    return {
        "status": "archived",
        "case_id": case.case_id,
        "date": date_key,
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "metadata_path": str(metadata_path),
        "integrity_hash": integrity_hash,
        "webhook": webhook_result,
    }


def _send_archive_webhook(payload: dict) -> dict:
    settings = get_settings()
    url = (settings.tier4_archive_webhook_url or "").strip()
    if not url:
        return {"status": "skipped", "reason": "webhook_not_configured"}

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ghostrescue-tier4-archive/1.0",
    }
    if settings.tier4_archive_webhook_bearer_token:
        headers["Authorization"] = f"Bearer {settings.tier4_archive_webhook_bearer_token}"

    req = urllib_request.Request(url=url, data=body, headers=headers, method="POST")
    timeout_seconds = max(0.5, float(settings.tier4_archive_webhook_timeout_seconds or 5.0))
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
            return {
                "status": "sent",
                "http_status": int(getattr(resp, "status", 200) or 200),
            }
    except urllib_error.HTTPError as exc:
        return {
            "status": "failed",
            "http_status": int(exc.code),
            "reason": "http_error",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "reason": str(exc),
        }


@router.get("/tier4-proof/report.pdf")
async def tier4_proof_report(case_id: str | None = None, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    case, proof = await _resolve_tier4_case_and_proof(db, case_id)

    pdf_bytes, _, _, _ = await _tier4_report_materials(db, case, proof)
    file_name = f"ghostrescue-tier4-proof-{case.case_id}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.post("/tier4-proof/auto-export")
async def tier4_proof_auto_export(
    case_id: str | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case, proof = await _resolve_tier4_case_and_proof(db, case_id)

    settings = get_settings()
    export_root = Path(settings.tier4_audit_export_root)
    if not export_root.is_absolute():
        export_root = Path.cwd() / export_root

    index_path = export_root / "export_index.json"
    export_root.mkdir(parents=True, exist_ok=True)

    index: dict[str, dict] = {}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}

    case_updated_at = case.updated_at.isoformat() if case.updated_at else ""
    existing_entry = index.get(case.case_id)
    if (
        existing_entry
        and existing_entry.get("case_updated_at") == case_updated_at
        and not force
    ):
        return {
            "exported": False,
            "reason": "already_exported_current_case_state",
            "case_id": case.case_id,
            "exported_pdf": existing_entry.get("pdf_path"),
            "exported_metadata": existing_entry.get("metadata_path"),
            "exported_at": existing_entry.get("exported_at"),
        }

    signals = (
        await db.scalars(select(Signal).where(Signal.signal_id.in_(case.signal_ids or [])))
    ).all()
    feedback_rows = (
        await db.scalars(
            select(AnalystFeedback)
            .where(AnalystFeedback.case_id == case.case_id)
            .order_by(desc(AnalystFeedback.created_at))
            .limit(200)
        )
    ).all()
    explainability = await ExplainabilityService(db).case_explainability(case.case_id)
    pdf_bytes = _render_tier4_pdf(case, proof, explainability, signals, feedback_rows)

    now = datetime.now(UTC)
    date_folder = now.strftime("%Y/%m/%d")
    stamped_dir = export_root / date_folder
    stamped_dir.mkdir(parents=True, exist_ok=True)
    stamped = now.strftime("%Y%m%dT%H%M%SZ")
    safe_case_id = _safe_case_id(case.case_id)

    file_stem = f"ghostrescue-tier4-proof-{safe_case_id}-{stamped}"
    pdf_path = stamped_dir / f"{file_stem}.pdf"
    meta_path = stamped_dir / f"{file_stem}.json"

    pdf_path.write_bytes(pdf_bytes)
    metadata = {
        "case_id": case.case_id,
        "exported_at": now.isoformat(),
        "case_updated_at": case_updated_at,
        "proof": proof,
    }
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    index[case.case_id] = {
        "exported_at": now.isoformat(),
        "case_updated_at": case_updated_at,
        "pdf_path": str(pdf_path),
        "metadata_path": str(meta_path),
    }
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "exported": True,
        "case_id": case.case_id,
        "exported_at": now.isoformat(),
        "exported_pdf": str(pdf_path),
        "exported_metadata": str(meta_path),
        "audit_root": str(export_root),
    }


@router.post("/tier4-proof/archive")
async def tier4_proof_archive(case_id: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    case, proof = await _resolve_tier4_case_and_proof(db, case_id)
    return await _archive_tier4_case(db, case, proof)


@router.get("/tier4-proof/archive")
async def tier4_proof_archive_list(date: str | None = None, case_id: str | None = None) -> dict:
    root = _archive_root_path()
    index = _read_json_file(root / "archive_index.json")

    if case_id:
        found = index.get(case_id)
        return {
            "query": {"case_id": case_id, "date": date},
            "count": 1 if found else 0,
            "results": [found] if found else [],
        }

    if date:
        day_dir = root / date
        metadata = _read_json_file(day_dir / "metadata.json")
        cases = metadata.get("cases") if isinstance(metadata.get("cases"), list) else []
        return {
            "query": {"date": date},
            "count": len(cases),
            "results": cases,
            "metadata_path": str(day_dir / "metadata.json"),
        }

    results = [v for v in index.values() if isinstance(v, dict)]
    results.sort(key=lambda row: str(row.get("archived_at") or ""), reverse=True)
    return {
        "query": {},
        "count": len(results),
        "results": results,
    }


@router.get("/tier4-proof/verify")
async def tier4_proof_verify(case_id: str) -> dict:
    root = _archive_root_path()
    index = _read_json_file(root / "archive_index.json")
    record = index.get(case_id)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Archived case not found")

    pdf_path = record.get("pdf_path")
    json_path = record.get("json_path")
    stored_hash = record.get("integrity_hash")

    if not stored_hash and json_path:
        artifact = _read_json_file(Path(json_path))
        if isinstance(artifact, dict):
            stored_hash = artifact.get("integrity_hash")

    recomputed_hash = _derive_integrity_hash_from_files(pdf_path, json_path)
    verification_mode = "stored_hash"
    if not stored_hash and recomputed_hash:
        # Legacy records may predate integrity_hash persistence; backfill on first verify.
        stored_hash = recomputed_hash
        verification_mode = "derived_baseline"
        record["integrity_hash"] = stored_hash
        _write_json_file(root / "archive_index.json", index)
        if json_path and Path(json_path).exists():
            artifact_payload = _read_json_file(Path(json_path))
            if isinstance(artifact_payload, dict):
                artifact_payload["integrity_hash"] = stored_hash
                _write_json_file(Path(json_path), artifact_payload)

    match = bool(stored_hash and recomputed_hash and stored_hash == recomputed_hash)

    return {
        "case_id": case_id,
        "valid": bool(match),
        "stored_hash": stored_hash,
        "recomputed_hash": recomputed_hash,
        "match": bool(match),
        "verification_mode": verification_mode,
        "pdf_exists": bool(pdf_path and Path(pdf_path).exists()),
        "json_exists": bool(json_path and Path(json_path).exists()),
        "archived_at": record.get("archived_at"),
    }


@router.get("/tier4-proof")
async def tier4_proof(db: AsyncSession = Depends(get_db)) -> dict:
    proof = await _tier4_proof_artifact(db)
    if proof.get("found") and get_settings().tier4_archive_auto_trigger:
        case = await db.scalar(select(Case).where(Case.case_id == proof.get("case_id")))
        if case:
            archive_result = await _archive_tier4_case(db, case, proof)
            proof["archive"] = archive_result
    return proof


@router.get("/performance")
async def system_performance(db: AsyncSession = Depends(get_db)) -> dict:
    cache = CasePriorityService.corroboration_cache_metrics()
    quality = CasePriorityService.corroboration_quality_metrics()
    if int(quality.get("samples") or 0) == 0:
        quality = await _fallback_quality_from_recent_cases(db)
    source_contribution = await _source_contribution_panel(db)
    alerts = _build_quality_alerts(cache, quality)
    health = _system_health(cache, quality, alerts)

    feedback_telemetry = await _decision_telemetry(db)

    return {
        "corroboration_cache": cache,
        "corroboration_quality": quality,
        "source_contribution": source_contribution,
        "quality_targets": QUALITY_TARGETS,
        "alerts": alerts,
        "system_health": health,
        "feedback_telemetry": feedback_telemetry,
    }


async def _decision_telemetry(db: AsyncSession) -> dict:
    """Decision-weight observability for the analyst feedback loop."""
    now = datetime.now(UTC)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    # SQLite may return timezone-naive datetimes; use naive UTC for in-Python comparison
    cutoff_7d_naive = cutoff_7d.replace(tzinfo=None)
    cutoff_30d_naive = cutoff_30d.replace(tzinfo=None)

    # Known per-action priority lift estimates (from _feedback_bonus constants)
    _LIFT_ESTIMATE = {
        "confirm_convergence": 0.9,
        "reject_correlation": -2.2,
        "mark_high_priority": 1.8,
    }

    def _naive(ts):
        return ts.replace(tzinfo=None) if ts and ts.tzinfo else ts

    rows_30d = (
        await db.scalars(
            select(AnalystFeedback)
            .order_by(AnalystFeedback.created_at.desc())
            .limit(2000)
        )
    ).all()
    # Filter in Python to avoid tz-aware cutoff issues in SQL query
    rows_30d = [r for r in rows_30d if _naive(r.created_at) >= cutoff_30d_naive]

    counts_7d: dict[str, int] = {
        "confirm_convergence": 0,
        "reject_correlation": 0,
        "mark_high_priority": 0,
        "other": 0,
    }
    counts_30d: dict[str, int] = {
        "confirm_convergence": 0,
        "reject_correlation": 0,
        "mark_high_priority": 0,
        "other": 0,
    }
    cases_with_decisions_30d: set[str] = set()
    rejected_cases_30d: set[str] = set()
    confirmed_after_rejected: set[str] = set()
    roles = ("junior_analyst", "senior_analyst", "trusted_operator")
    decisions_by_role: dict[str, int] = {role: 0 for role in roles}
    role_lift_sum: dict[str, float] = {role: 0.0 for role in roles}
    role_lift_count: dict[str, int] = {role: 0 for role in roles}
    role_case_ids: dict[str, set[str]] = {role: set() for role in roles}
    rejected_cases_by_role: dict[str, set[str]] = {role: set() for role in roles}
    confirmed_after_rejected_by_role: dict[str, set[str]] = {role: set() for role in roles}

    for row in rows_30d:
        dt = parse_decision_type(row.notes) or "other"
        role = parse_decision_role(row.notes)
        counts_30d[dt] = counts_30d.get(dt, 0) + 1
        cases_with_decisions_30d.add(row.case_id)
        if role in decisions_by_role:
            decisions_by_role[role] += 1
            role_case_ids[role].add(row.case_id)
            if dt in _LIFT_ESTIMATE:
                weighted_lift = _LIFT_ESTIMATE[dt] * decision_weight_for_notes(row.notes)
                role_lift_sum[role] += weighted_lift
                role_lift_count[role] += 1
        if dt == "reject_correlation":
            rejected_cases_30d.add(row.case_id)
            if role in rejected_cases_by_role:
                rejected_cases_by_role[role].add(row.case_id)
        if _naive(row.created_at) >= cutoff_7d_naive:
            counts_7d[dt] = counts_7d.get(dt, 0) + 1

    # False-correlation rate: cases that were rejected but also re-confirmed
    for row in rows_30d:
        if (
            parse_decision_type(row.notes) == "confirm_convergence"
            and row.case_id in rejected_cases_30d
        ):
            confirmed_after_rejected.add(row.case_id)
            for role, rejected_case_ids in rejected_cases_by_role.items():
                if row.case_id in rejected_case_ids:
                    confirmed_after_rejected_by_role[role].add(row.case_id)

    false_correlation_rate = round(
        len(confirmed_after_rejected) / max(1, len(rejected_cases_30d)), 3
    )

    # Top-queue influence: % of top-50 priority cases influenced by analyst decisions
    top_queue_influence_pct = 0.0
    top_queue_influence_by_role: dict[str, float] = {role: 0.0 for role in roles}
    try:
        recent_cases = (
            await db.scalars(
                select(Case).order_by(desc(Case.updated_at)).limit(200)
            )
        ).all()
        if recent_cases:
            slice_50 = recent_cases[:50]
            scored = await CasePriorityService(db).score_cases(slice_50, apply_saturation=True)
            by_priority = sorted(
                slice_50,
                key=lambda c: scored.get(c.case_id, {}).get("priority_score", 0),
                reverse=True,
            )
            top50_ids = {c.case_id for c in by_priority[:50]}
            influenced = top50_ids & cases_with_decisions_30d
            top_queue_influence_pct = round(len(influenced) / max(1, len(top50_ids)), 3)
            for role in roles:
                role_influenced = top50_ids & role_case_ids[role]
                top_queue_influence_by_role[role] = round(len(role_influenced) / max(1, len(top50_ids)), 3)
    except Exception:
        pass

    total_30d = sum(counts_30d.values())
    avg_priority_lift_by_role = {
        role: round(role_lift_sum[role] / max(1, role_lift_count[role]), 3)
        for role in roles
    }
    false_correlation_rate_by_role = {
        role: round(
            len(confirmed_after_rejected_by_role[role]) / max(1, len(rejected_cases_by_role[role])),
            3,
        )
        for role in roles
    }

    return {
        "decision_counts": {
            "7_days": dict(counts_7d),
            "30_days": dict(counts_30d),
        },
        "avg_priority_lift_per_decision": {
            dt: _LIFT_ESTIMATE[dt]
            for dt in ["confirm_convergence", "reject_correlation", "mark_high_priority"]
        },
        "top_queue_influence_pct": top_queue_influence_pct,
        "false_correlation_rate": false_correlation_rate,
        "decisions_by_role": decisions_by_role,
        "avg_priority_lift_by_role": avg_priority_lift_by_role,
        "top_queue_influence_by_role": top_queue_influence_by_role,
        "false_correlation_rate_by_role": false_correlation_rate_by_role,
        "total_decisions_30d": total_30d,
    }
