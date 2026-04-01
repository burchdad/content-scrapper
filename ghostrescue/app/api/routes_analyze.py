from io import BytesIO
import json
import re
import secrets
import zipfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.case import Case
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.alert_intelligence_service import AlertIntelligenceService
from app.services.correlation_service import CorrelationService
from app.services.entity_memory_service import EntityMemoryService
from app.services.nlp.classifier import NLPClassifier
from app.services.scoring.risk_scorer import RiskScorer
from app.services.trust_service import TrustService

router = APIRouter(prefix="/api/v1", tags=["analysis"])
settings = get_settings()

_classifier = NLPClassifier()
_scorer = RiskScorer()
_TEMP_INVESTIGATION_SESSIONS: dict[str, dict[str, Any]] = {}


def _no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, private",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }


def _trim_chat_messages(messages: list[dict]) -> list[dict]:
    max_messages = max(2, int(settings.temporary_chat_max_messages or 12))
    safe: list[dict] = []
    for msg in messages[-max_messages:]:
        role = str(msg.get("role") or "user").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        safe.append({"role": role, "content": content[:4000]})
    return safe


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _prune_temporary_sessions() -> None:
    now = _utc_now()
    expired = [sid for sid, data in _TEMP_INVESTIGATION_SESSIONS.items() if (data.get("expires_at") or now) <= now]
    for sid in expired:
        _TEMP_INVESTIGATION_SESSIONS.pop(sid, None)


def _new_temporary_session_id() -> str:
    return f"tis_{secrets.token_urlsafe(18)}"


def _allowed_sensitive_roles() -> set[str]:
    raw = settings.temporary_sensitive_allowed_roles or ""
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def _normalize_role(role: str | None) -> str:
    return (role or "").strip().lower()


def _enforce_sensitive_role(analyst_role: str | None) -> str:
    role = _normalize_role(analyst_role)
    allowed = _allowed_sensitive_roles()
    if not role:
        raise HTTPException(status_code=403, detail="Sensitive mode requires analyst role")
    if allowed and role not in allowed:
        raise HTTPException(status_code=403, detail=f"Role '{role}' is not authorized for sensitive mode")
    return role


def _build_signal_timeline(file_insights: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, info in enumerate(file_insights, start=1):
        out.append(
            {
                "sequence": i,
                "file_name": info.get("file_name"),
                "signal_types": info.get("signal_types") or [],
                "strong_signal_count": info.get("strong_signal_count") or 0,
                "excerpt": (info.get("excerpt") or "")[:180],
            }
        )
    return out


async def _temporary_chat_completion(context: str, messages: list[dict]) -> dict:
    if settings.openai_api_key:
        system_prompt = (
            "You are an investigative intelligence assistant for law-enforcement workflows. "
            "Use neutral, factual language; provide leads and suggestions only; no legal conclusions. "
            "Do not claim certainty. Focus on actionable next steps and possible persons of interest from provided context."
        )
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "Security constraints: this is temporary investigation chat; do not reference persistence; "
                        "never output raw secrets; avoid speculation beyond evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Investigation context:\n{context[:int(settings.temporary_chat_max_context_chars)]}",
                },
                *messages,
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = ((((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or "").strip()
        return {"provider": "openai", "reply": text}

    # Safe fallback if no LLM credentials are configured
    last_user = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
    return {
        "provider": "local_fallback",
        "reply": (
            "Temporary secure chat fallback is active (no LLM key configured). "
            "Use the temporary report signals and suggested case matches to continue triage. "
            f"Latest question captured: {str(last_user)[:220]}"
        ),
    }


def _extract_text_from_document(file_name: str, payload: bytes) -> str:
    lower = file_name.lower()
    if lower.endswith((".txt", ".md", ".csv", ".json", ".log", ".xml")):
        if lower.endswith(".json"):
            try:
                obj = json.loads(payload.decode("utf-8", errors="ignore"))
                return json.dumps(obj, indent=2)
            except Exception:
                return payload.decode("utf-8", errors="ignore")
        return payload.decode("utf-8", errors="ignore")

    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # Optional dependency

            reader = PdfReader(BytesIO(payload))
            pages = [p.extract_text() or "" for p in reader.pages]
            return "\n".join(pages)
        except Exception:
            raw = payload.decode("latin-1", errors="ignore")
            return re.sub(r"[^\x20-\x7E\n\r\t]", " ", raw)

    if lower.endswith(".docx"):
        try:
            with zipfile.ZipFile(BytesIO(payload)) as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", doc_xml)
            return re.sub(r"\s+", " ", text)
        except Exception:
            return ""

    return ""


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if len(t) >= 3}


def _documents_overlap_features(docs: list[dict]) -> dict:
    token_sets = [set(d.get("_tokens") or []) for d in docs if d.get("extractable")]
    if len(token_sets) < 2:
        return {
            "documents_compared": len(token_sets),
            "overlap_score": 0.0,
            "shared_terms": [],
        }
    common = set.intersection(*token_sets) if token_sets else set()
    union = set.union(*token_sets) if token_sets else set()
    overlap = round(len(common) / max(1, len(union)), 3)
    top_terms = sorted(common, key=len, reverse=True)[:15]
    return {
        "documents_compared": len(token_sets),
        "overlap_score": overlap,
        "shared_terms": top_terms,
    }


async def _suggest_case_matches(db: AsyncSession, combined_text: str) -> list[dict]:
    recent_cases = (
        await db.scalars(select(Case).order_by(desc(Case.updated_at)).limit(120))
    ).all()
    incoming = _token_set(combined_text)
    if not incoming:
        return []
    matches: list[dict] = []
    for case in recent_cases:
        hay = f"{case.explanation or ''} {' '.join(case.entity_ids or [])} {' '.join(case.signal_ids or [])}"
        case_tokens = _token_set(hay)
        if not case_tokens:
            continue
        jaccard = len(incoming & case_tokens) / max(1, len(incoming | case_tokens))
        if jaccard < 0.02:
            continue
        matches.append(
            {
                "case_id": case.case_id,
                "status": case.status,
                "risk_score": float(case.risk_score or 0.0),
                "match_score": round(jaccard, 3),
            }
        )
    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches[:5]


def _documents_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "documents"


def _documents_index_path() -> Path:
    return _documents_root() / "index.json"


def _load_documents_index() -> list[dict]:
    p = _documents_index_path()
    if not p.exists():
        return []
    try:
        out = json.loads(p.read_text(encoding="utf-8"))
        return out if isinstance(out, list) else []
    except Exception:
        return []


def _save_documents_index(rows: list[dict]) -> None:
    p = _documents_index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", name or "document")
    return cleaned.strip(".-") or "document"


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_text(
    request: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> AnalyzeResponse:
    """
    Run NLP classification and risk scoring on a text snippet.

    Detects coercion language, recruitment patterns, minor-risk indicators,
    commercial sex signals, off-platform contact diversion, and location patterns.

    **All outputs are intelligence leads only — not verified conclusions.**
    Human review is required before any action is taken.
    """
    signals = _classifier.classify(request.text)
    correlation_service = CorrelationService(db)
    memory_service = EntityMemoryService(db)
    alert_service = AlertIntelligenceService(db)

    correlation = (
        await correlation_service.entity_correlation_features(request.entity_id)
        if request.entity_id
        else {
            "source_diversity": 0,
            "cross_source_reinforcement": 0.0,
            "shared_identifier_hits": 0,
            "temporal_burst_24h": 0,
        }
    )

    penalty = await TrustService(db).adaptive_penalty()
    score_result = _scorer.score(
        signals=signals,
        entity_match_confidence=max(0.0, min(1.0, 0.5 + correlation.get("cross_source_reinforcement", 0.0) / 2)),
        signal_frequency_bonus=float(correlation.get("temporal_burst_24h", 0)),
        calibration_penalty=penalty,
        source_names=[request.source_name] * len(signals) if request.source_name else None,
    )

    case_id: str | None = None
    alert_id: str | None = None

    if request.entity_id:
        case, alert = await alert_service.evaluate_and_create_case(
            entity_id=request.entity_id,
            risk_score=score_result.risk_score,
            confidence_score=score_result.confidence_score,
            system_confidence=score_result.system_confidence,
            explanation=score_result.explanation,
            signals=signals,
            correlation=correlation,
        )
        case_id = case.case_id
        alert_id = alert.alert_id if alert else None
        await memory_service.record_event(
            entity_id=request.entity_id,
            event_type="analysis",
            summary=f"Analysis produced risk={score_result.risk_score:.1f} with {len(signals)} signals.",
            source_name=request.source_name,
            source_url=request.source_url,
            metadata={
                "risk_score": score_result.risk_score,
                "confidence_score": score_result.confidence_score,
                "signal_types": [s.signal_type for s in signals],
                "case_id": case_id,
                "alert_id": alert_id,
            },
        )

    return AnalyzeResponse(
        entity_id=request.entity_id,
        signals=signals,
        risk_score=score_result.risk_score,
        confidence_score=score_result.confidence_score,
        system_confidence=score_result.system_confidence,
        explanation=score_result.explanation,
        case_id=case_id,
        alert_id=alert_id,
        disclaimer=settings.disclaimer,
    )


@router.post("/analyze/documents-temporary")
async def analyze_documents_temporary(
    files: list[UploadFile] = File(...),
    analyst_context: str | None = Form(default=None),
    entity_id: str | None = Form(default=None),
    sensitive_mode: bool = Form(default=False),
    analyst_id: str | None = Form(default=None),
    analyst_role: str | None = Form(default=None),
    x_investigation_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Analyze uploaded documents in-memory only. Files are not stored or linked to cases."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    _prune_temporary_sessions()
    access_key = (settings.temporary_chat_access_key or "").strip()
    normalized_role = _normalize_role(analyst_role)
    if sensitive_mode and access_key and x_investigation_key != access_key:
        raise HTTPException(status_code=403, detail="Sensitive mode requires a valid investigation access key")
    if sensitive_mode:
        normalized_role = _enforce_sensitive_role(analyst_role)
        if not (analyst_id or "").strip():
            raise HTTPException(status_code=403, detail="Sensitive mode requires analyst_id")

    extracted_docs: list[dict] = []
    combined_parts: list[str] = []
    buffered_files: list[dict] = []
    file_insights: list[dict] = []

    for f in files:
        payload = await f.read()
        text = _extract_text_from_document(f.filename or "document", payload)
        text = text.strip()
        doc_signals = _classifier.classify(text[:12000]) if text else []
        doc_signal_types = sorted({s.signal_type for s in doc_signals})[:6]
        doc_strong = sum(1 for s in doc_signals if float(s.confidence or 0.0) >= 0.7)
        tokens = _token_set(text)
        extracted_docs.append(
            {
                "file_name": f.filename or "document",
                "content_type": f.content_type or "application/octet-stream",
                "size_bytes": len(payload),
                "extractable": bool(text),
                "extracted_chars": len(text),
                "_tokens": sorted(tokens),
            }
        )
        buffered_files.append(
            {
                "file_name": f.filename or "document",
                "content_type": f.content_type or "application/octet-stream",
                "payload_b64": payload.hex(),
            }
        )
        file_insights.append(
            {
                "file_name": f.filename or "document",
                "signal_types": doc_signal_types,
                "strong_signal_count": doc_strong,
                "excerpt": text,
            }
        )
        if text:
            combined_parts.append(f"[FILE: {f.filename}]\n{text[:15000]}")

    if analyst_context:
        combined_parts.append(f"[ANALYST CONTEXT]\n{analyst_context}")

    combined_text = "\n\n".join(combined_parts).strip()
    if not combined_text:
        return JSONResponse(content={
            "status": "no_extractable_content",
            "documents": extracted_docs,
            "report": {
                "summary": "No extractable text was found in the uploaded documents.",
                "signals": [],
                "risk_score": 0.0,
                "confidence_score": 0.0,
                "system_confidence": 0.0,
                "explanation": "Upload text/PDF/DOCX content with machine-readable text.",
            },
            "temporary": True,
            "stored": False,
            "disclaimer": settings.disclaimer,
        }, headers=_no_store_headers())

    signals = _classifier.classify(combined_text[:50000])
    correlation = (
        await CorrelationService(db).entity_correlation_features(entity_id)
        if entity_id
        else {
            "source_diversity": 0,
            "cross_source_reinforcement": 0.0,
            "shared_identifier_hits": 0,
            "temporal_burst_24h": 0,
        }
    )
    penalty = await TrustService(db).adaptive_penalty()
    score_result = _scorer.score(
        signals=signals,
        entity_match_confidence=max(0.0, min(1.0, 0.5 + correlation.get("cross_source_reinforcement", 0.0) / 2)),
        signal_frequency_bonus=float(correlation.get("temporal_burst_24h", 0)),
        calibration_penalty=penalty,
        source_names=["temporary_document_upload"] * len(signals),
    )

    top_signals = [
        {
            "signal_type": s.signal_type,
            "label": s.label,
            "confidence": float(s.confidence),
            "evidence": (s.evidence or "")[:280],
        }
        for s in sorted(signals, key=lambda x: float(x.confidence), reverse=True)[:8]
    ]
    strong_count = sum(1 for s in top_signals if float(s.get("confidence") or 0.0) >= 0.7)
    overlap = _documents_overlap_features(extracted_docs)
    suggestions = await _suggest_case_matches(db, combined_text)
    timeline = _build_signal_timeline(file_insights)

    for d in extracted_docs:
        d.pop("_tokens", None)

    session_id = _new_temporary_session_id()
    now = _utc_now()
    ttl_minutes = max(5, int(settings.temporary_session_ttl_minutes or 90))
    expires_at = now.replace(microsecond=0) + timedelta(minutes=ttl_minutes)
    _TEMP_INVESTIGATION_SESSIONS[session_id] = {
        "session_id": session_id,
        "created_at": now,
        "expires_at": expires_at,
        "sensitive_mode": bool(sensitive_mode),
        "analyst_id": (analyst_id or "").strip() or None,
        "analyst_role": normalized_role or None,
        "entity_id": entity_id,
        "analyst_context": analyst_context or "",
        "combined_text": combined_text[: int(settings.temporary_chat_max_context_chars)],
        "documents": extracted_docs,
        "buffered_files": buffered_files,
        "report": {
            "signals": top_signals,
            "risk_score": score_result.risk_score,
            "confidence_score": score_result.confidence_score,
            "system_confidence": score_result.system_confidence,
            "strong_signal_count": strong_count,
            "explanation": score_result.explanation,
        },
        "document_correlation": overlap,
        "case_suggestions": suggestions,
        "signal_timeline": timeline,
        "chat_history": [],
    }

    return JSONResponse(content={
        "status": "analyzed",
        "session_id": session_id,
        "session_expires_at": expires_at.isoformat(),
        "temporary": True,
        "stored": False,
        "sensitive_mode": bool(sensitive_mode),
        "temporary_disclaimer": (
            "Temporary analysis only: uploaded documents were analyzed in-memory and were not "
            "stored or verified as system evidence."
        ),
        "documents": extracted_docs,
        "document_correlation": overlap,
        "case_suggestions": suggestions,
        "signal_timeline": timeline,
        "report": {
            "summary": (
                f"Temporary analysis completed for {len(files)} document(s). "
                f"Detected {len(signals)} signal(s) with risk score {score_result.risk_score:.1f}."
            ),
            "signals": top_signals,
            "strong_signal_count": strong_count,
            "risk_score": score_result.risk_score,
            "confidence_score": score_result.confidence_score,
            "system_confidence": score_result.system_confidence,
            "explanation": score_result.explanation,
        },
        "disclaimer": settings.disclaimer,
    }, headers=_no_store_headers())


@router.post("/analyze/documents-temporary/chat")
async def temporary_documents_chat(
    session_id: str | None = Form(default=None),
    user_message: str | None = Form(default=None),
    document_context: str | None = Form(default=None),
    messages_json: str | None = Form(default=None),
    analyst_id: str | None = Form(default=None),
    analyst_role: str | None = Form(default=None),
    x_investigation_key: str | None = Header(default=None),
) -> JSONResponse:
    """Secure, non-persistent chat over temporary document analysis context."""
    if not settings.temporary_chat_enabled:
        raise HTTPException(status_code=403, detail="Temporary chat is disabled")

    access_key = (settings.temporary_chat_access_key or "").strip()
    if access_key and x_investigation_key != access_key:
        raise HTTPException(status_code=403, detail="Invalid investigation access key")

    _prune_temporary_sessions()
    context = (document_context or "").strip()
    messages: list[dict] = []
    active_session: dict[str, Any] | None = None

    if session_id:
        active_session = _TEMP_INVESTIGATION_SESSIONS.get(session_id)
        if not active_session:
            raise HTTPException(status_code=404, detail="Temporary investigation session not found or expired")
        if active_session.get("sensitive_mode") and access_key and x_investigation_key != access_key:
            raise HTTPException(status_code=403, detail="Sensitive session requires a valid investigation access key")
        if active_session.get("sensitive_mode"):
            role = _enforce_sensitive_role(analyst_role)
            expected_role = _normalize_role(active_session.get("analyst_role"))
            expected_id = (active_session.get("analyst_id") or "").strip()
            if expected_role and role != expected_role:
                raise HTTPException(status_code=403, detail="Analyst role mismatch for sensitive session")
            if expected_id and (analyst_id or "").strip() != expected_id:
                raise HTTPException(status_code=403, detail="Analyst identity mismatch for sensitive session")

        context = active_session.get("combined_text") or context
        history = active_session.get("chat_history") or []
        if user_message:
            history.append({"role": "user", "content": str(user_message)[:2000]})
        messages = _trim_chat_messages(history)
    else:
        if not messages_json:
            raise HTTPException(status_code=400, detail="messages_json is required when session_id is not provided")
        try:
            parsed = json.loads(messages_json)
            if not isinstance(parsed, list):
                raise ValueError("messages_json must be a list")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid messages_json: {exc}") from exc
        messages = _trim_chat_messages(parsed)

    if not context:
        raise HTTPException(status_code=400, detail="document_context is required")

    completion = await _temporary_chat_completion(context, messages)
    if active_session is not None:
        active_session_history = active_session.get("chat_history") or []
        if user_message:
            active_session_history.append({"role": "user", "content": str(user_message)[:2000]})
        active_session_history.append({"role": "assistant", "content": str(completion.get("reply") or "")[:4000]})
        active_session["chat_history"] = _trim_chat_messages(active_session_history)
    body = {
        "status": "ok",
        "temporary": True,
        "stored": False,
        "session_id": session_id,
        "temporary_disclaimer": (
            "Secure temporary chat: conversation context is processed for this response only and is not "
            "stored as case evidence unless explicitly converted."
        ),
        "provider": completion.get("provider"),
        "reply": completion.get("reply"),
    }
    return JSONResponse(content=body, headers=_no_store_headers())


@router.delete("/analyze/documents-temporary/session/{session_id}")
async def clear_temporary_investigation_session(
    session_id: str,
    analyst_id: str | None = Header(default=None),
    analyst_role: str | None = Header(default=None),
    x_investigation_key: str | None = Header(default=None),
) -> JSONResponse:
    _prune_temporary_sessions()
    sess = _TEMP_INVESTIGATION_SESSIONS.get(session_id)
    if not sess:
        return JSONResponse(content={"status": "cleared", "session_id": session_id, "existed": False}, headers=_no_store_headers())

    access_key = (settings.temporary_chat_access_key or "").strip()
    if sess.get("sensitive_mode") and access_key and x_investigation_key != access_key:
        raise HTTPException(status_code=403, detail="Sensitive session requires a valid investigation access key")
    if sess.get("sensitive_mode"):
        role = _enforce_sensitive_role(analyst_role)
        expected_role = _normalize_role(sess.get("analyst_role"))
        expected_id = (sess.get("analyst_id") or "").strip()
        if expected_role and role != expected_role:
            raise HTTPException(status_code=403, detail="Analyst role mismatch for sensitive session")
        if expected_id and (analyst_id or "").strip() != expected_id:
            raise HTTPException(status_code=403, detail="Analyst identity mismatch for sensitive session")

    _TEMP_INVESTIGATION_SESSIONS.pop(session_id, None)
    return JSONResponse(content={"status": "cleared", "session_id": session_id, "existed": True}, headers=_no_store_headers())


@router.post("/analyze/documents-temporary/convert")
async def convert_temporary_documents_to_case(
    files: list[UploadFile] | None = File(default=None),
    analyst_context: str | None = Form(default=None),
    entity_id: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    source_name: str = Form(default="temporary_promoted_upload"),
    persist_documents: bool = Form(default=True),
    analyst_id: str | None = Form(default=None),
    analyst_role: str | None = Form(default=None),
    x_investigation_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Promote temporary uploaded documents into a persistent case and optional stored files."""
    _prune_temporary_sessions()

    session_data: dict[str, Any] | None = None
    if session_id:
        session_data = _TEMP_INVESTIGATION_SESSIONS.get(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Temporary investigation session not found or expired")
        access_key = (settings.temporary_chat_access_key or "").strip()
        if session_data.get("sensitive_mode") and access_key and x_investigation_key != access_key:
            raise HTTPException(status_code=403, detail="Sensitive session requires a valid investigation access key")
        if session_data.get("sensitive_mode"):
            role = _enforce_sensitive_role(analyst_role)
            expected_role = _normalize_role(session_data.get("analyst_role"))
            expected_id = (session_data.get("analyst_id") or "").strip()
            if expected_role and role != expected_role:
                raise HTTPException(status_code=403, detail="Analyst role mismatch for sensitive session")
            if expected_id and (analyst_id or "").strip() != expected_id:
                raise HTTPException(status_code=403, detail="Analyst identity mismatch for sensitive session")

    if not files and not session_data:
        raise HTTPException(status_code=400, detail="No files provided and no session_id provided")

    extracted_parts: list[str] = []
    buffered_files: list[tuple[str, str, bytes]] = []
    if session_data:
        for b in session_data.get("buffered_files") or []:
            name = str(b.get("file_name") or "document")
            ctype = str(b.get("content_type") or "application/octet-stream")
            payload = bytes.fromhex(str(b.get("payload_b64") or "")) if b.get("payload_b64") else b""
            buffered_files.append((name, ctype, payload))
            txt = _extract_text_from_document(name, payload).strip()
            if txt:
                extracted_parts.append(f"[FILE: {name}]\n{txt[:18000]}")
    if files:
        for f in files:
            payload = await f.read()
            buffered_files.append((f.filename or "document", f.content_type or "application/octet-stream", payload))
            txt = _extract_text_from_document(f.filename or "document", payload).strip()
            if txt:
                extracted_parts.append(f"[FILE: {f.filename}]\n{txt[:18000]}")

    if analyst_context:
        extracted_parts.append(f"[ANALYST CONTEXT]\n{analyst_context}")
    elif session_data and session_data.get("analyst_context"):
        extracted_parts.append(f"[ANALYST CONTEXT]\n{session_data.get('analyst_context')}")

    if not entity_id and session_data:
        entity_id = session_data.get("entity_id")
    if not entity_id:
        raise HTTPException(status_code=400, detail="entity_id is required")

    combined_text = "\n\n".join(extracted_parts).strip()
    if not combined_text:
        raise HTTPException(status_code=400, detail="No extractable text from uploaded files")

    correlation_service = CorrelationService(db)
    alert_service = AlertIntelligenceService(db)
    memory_service = EntityMemoryService(db)

    signals = _classifier.classify(combined_text[:50000])
    correlation = await correlation_service.entity_correlation_features(entity_id)
    penalty = await TrustService(db).adaptive_penalty()
    score_result = _scorer.score(
        signals=signals,
        entity_match_confidence=max(0.0, min(1.0, 0.5 + correlation.get("cross_source_reinforcement", 0.0) / 2)),
        signal_frequency_bonus=float(correlation.get("temporal_burst_24h", 0)),
        calibration_penalty=penalty,
        source_names=[source_name] * len(signals),
    )

    case, alert = await alert_service.evaluate_and_create_case(
        entity_id=entity_id,
        risk_score=score_result.risk_score,
        confidence_score=score_result.confidence_score,
        system_confidence=score_result.system_confidence,
        explanation=score_result.explanation,
        signals=signals,
        correlation=correlation,
    )

    now = datetime.now(UTC)
    persisted_docs: list[dict] = []
    if persist_documents:
        date_folder = now.strftime("%Y-%m-%d")
        day_dir = _documents_root() / date_folder
        day_dir.mkdir(parents=True, exist_ok=True)
        index = _load_documents_index()

        for file_name, content_type, payload in buffered_files:
            doc_id = f"doc-{uuid.uuid4().hex[:12]}"
            stored_name = f"{doc_id}-{_safe_filename(file_name)}"
            path = day_dir / stored_name
            path.write_bytes(payload)
            row = {
                "doc_id": doc_id,
                "file_name": file_name,
                "stored_path": str(path),
                "size_bytes": len(payload),
                "content_type": content_type,
                "case_id": case.case_id,
                "source_name": source_name,
                "notes": "promoted_from_temporary",
                "imported_at": now.isoformat(),
            }
            persisted_docs.append(row)
            index.append(row)
        _save_documents_index(index)

        meta = dict(case.extra_metadata or {})
        existing = meta.get("document_ids") if isinstance(meta.get("document_ids"), list) else []
        existing.extend([d["doc_id"] for d in persisted_docs])
        meta["document_ids"] = sorted(set(existing))
        meta["document_count"] = len(meta["document_ids"])
        case.extra_metadata = meta
        case.updated_at = now
        await db.commit()

    await memory_service.record_event(
        entity_id=entity_id,
        event_type="temporary_docs_promoted",
        summary=(
            f"Temporary document analysis promoted to case {case.case_id}; "
            f"signals={len(signals)}, persisted_docs={len(persisted_docs)}."
        ),
        source_name=source_name,
        metadata={
            "case_id": case.case_id,
            "alert_id": alert.alert_id if alert else None,
            "signal_count": len(signals),
            "persisted_docs": len(persisted_docs),
        },
    )

    return JSONResponse(content={
        "status": "converted",
        "case_id": case.case_id,
        "alert_id": alert.alert_id if alert else None,
        "risk_score": score_result.risk_score,
        "system_confidence": score_result.system_confidence,
        "signal_count": len(signals),
        "persisted_documents": len(persisted_docs),
        "temporary": False,
        "stored": bool(persist_documents),
        "disclaimer": settings.disclaimer,
    }, headers=_no_store_headers())
