"""Staging Service — validates, normalises, and promotes staged intelligence signals.

Responsibilities
----------------
1. Accept raw scraper/external payloads (schema normalisation)
2. Run auto-validation rules (dedupe, minimum field presence, source check)
3. Persist to the staged_signals table with status=pending (or auto-approve if clean)
4. Provide analyst-facing approve / reject helpers
5. On approval — hand off to IngestPipeline to create/update Entity + Signal records

Auto-validation rules
---------------------
- Must have a non-empty canonical_name or at minimum a raw text field
- source_name must be recognisable (even if not approved for direct ingest)
- Length guards on all text fields
- Dedupe: if a staged item with identical (source_name, source_url) already exists
  in pending status, reject as duplicate
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staged_signal import StagedSignal
from app.services.source_registry import (
    TRUST_UNVALIDATED,
    get_trust_level,
    is_source_approved,
)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self) -> None:
        self.valid: bool = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.auto_approve: bool = False

    def fail(self, reason: str) -> "ValidationResult":
        self.valid = False
        self.errors.append(reason)
        return self

    def warn(self, msg: str) -> "ValidationResult":
        self.warnings.append(msg)
        return self


# ---------------------------------------------------------------------------
# Auto-validation rules
# ---------------------------------------------------------------------------

_MAX_NAME_LEN   = 512
_MAX_URL_LEN    = 2048
_MAX_TEXT_LEN   = 10_000
_MIN_NAME_LEN   = 2


def _auto_validate(payload: dict, source_name: str, source_url: str | None) -> ValidationResult:
    result = ValidationResult()

    # 1. Canonical name or fallback text must be present
    name = (
        payload.get("canonical_name")
        or payload.get("name")
        or payload.get("title")
        or ""
    ).strip()
    if len(name) < _MIN_NAME_LEN:
        result.fail("payload must include a non-empty name/title (min 2 characters)")

    # 2. Length guards
    if len(name) > _MAX_NAME_LEN:
        result.fail(f"canonical_name exceeds {_MAX_NAME_LEN} characters")
    if source_url and len(source_url) > _MAX_URL_LEN:
        result.fail(f"source_url exceeds {_MAX_URL_LEN} characters")

    raw_text = payload.get("raw_text", "")
    if raw_text and len(raw_text) > _MAX_TEXT_LEN:
        result.warn(f"raw_text truncated to {_MAX_TEXT_LEN} characters")

    # 3. Source must be at least recognisable
    if not source_name or len(source_name.strip()) < 2:
        result.fail("source_name is required (min 2 characters)")

    # 4. Approved sources can be auto-approved (their content is already trusted)
    if result.valid and is_source_approved(source_name):
        result.auto_approve = True

    return result


def _normalise(payload: dict, source_name: str) -> dict:
    """Extract well-known fields from a free-form scraper payload."""
    name = (
        payload.get("canonical_name")
        or payload.get("name")
        or payload.get("title")
        or ""
    ).strip()[:_MAX_NAME_LEN]

    raw_text = str(payload.get("raw_text") or payload.get("description") or "")[:_MAX_TEXT_LEN]

    return {
        "canonical_name": name,
        "entity_type": payload.get("entity_type", "person"),
        "detected_location": str(payload.get("location") or payload.get("city") or "")[:512] or None,
        "signal_type": payload.get("signal_type"),
        "confidence_baseline": float(payload.get("confidence") or 0.0),
        "raw_text_normalised": raw_text,
    }


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class StagingService:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def submit(
        self,
        source_name: str,
        source_url: str | None,
        raw_payload: dict[str, Any],
        submitted_by: str = "ghostscraper",
    ) -> dict[str, Any]:
        """Validate and persist a staged signal. Returns a status dict."""

        # Deduplicate by (source_name, source_url) — skip if already pending
        if source_url:
            existing = await self.db.execute(
                select(StagedSignal).where(
                    StagedSignal.source_name == source_name,
                    StagedSignal.source_url == source_url,
                    StagedSignal.status == "pending",
                )
            )
            if existing.scalars().first():
                return {
                    "status": "duplicate",
                    "reason": "A pending item from this source_url already exists.",
                }

        # Validate
        vr = _auto_validate(raw_payload, source_name, source_url)
        if not vr.valid:
            return {
                "status": "rejected",
                "errors": vr.errors,
                "warnings": vr.warnings,
            }

        # Normalise
        normalised = _normalise(raw_payload, source_name)
        trust = get_trust_level(source_name)

        record = StagedSignal(
            source_name=source_name,
            source_url=source_url,
            trust_level=trust,
            raw_payload=raw_payload,
            canonical_name=normalised["canonical_name"],
            entity_type=normalised["entity_type"],
            detected_location=normalised["detected_location"],
            signal_type=normalised.get("signal_type"),
            confidence_baseline=normalised["confidence_baseline"],
            status="approved" if vr.auto_approve else "pending",
            auto_validated=vr.auto_approve,
            validation_notes="; ".join(vr.warnings) if vr.warnings else None,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        return {
            "status": record.status,
            "staged_id": record.staged_id,
            "trust_level": trust,
            "auto_approved": vr.auto_approve,
            "warnings": vr.warnings,
        }

    # ------------------------------------------------------------------
    # Retrieve pending queue
    # ------------------------------------------------------------------

    async def list_queue(
        self,
        status: str = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = select(StagedSignal).where(StagedSignal.status == status)
        q = q.order_by(StagedSignal.submitted_at.asc()).limit(limit).offset(offset)
        rows = (await self.db.execute(q)).scalars().all()

        count_q = select(StagedSignal).where(StagedSignal.status == status)
        total = len((await self.db.execute(count_q)).scalars().all())

        return {
            "total": total,
            "returned": len(rows),
            "status_filter": status,
            "items": [_to_dict(r) for r in rows],
        }

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    async def approve(
        self,
        staged_id: str,
        reviewed_by: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        row = await self._get_or_404(staged_id)
        if row.status != "pending":
            return {"error": f"Item is already '{row.status}', cannot approve."}

        row.status = "approved"
        row.reviewed_by = reviewed_by
        row.reviewed_at = datetime.now(UTC)
        row.validation_notes = notes or row.validation_notes
        await self.db.commit()

        return {
            "staged_id": staged_id,
            "status": "approved",
            "message": (
                "Signal approved. It will be included in the next ingest cycle "
                "with trust_level='" + row.trust_level + "'."
            ),
        }

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    async def reject(
        self,
        staged_id: str,
        reviewed_by: str,
        reason: str,
    ) -> dict[str, Any]:
        row = await self._get_or_404(staged_id)
        if row.status != "pending":
            return {"error": f"Item is already '{row.status}', cannot reject."}

        row.status = "rejected"
        row.reviewed_by = reviewed_by
        row.reviewed_at = datetime.now(UTC)
        row.rejection_reason = reason
        await self.db.commit()

        return {"staged_id": staged_id, "status": "rejected", "reason": reason}

    # ------------------------------------------------------------------
    # Promote (approved → ingest pipeline)
    # ------------------------------------------------------------------

    async def list_approved_for_ingest(self, limit: int = 100) -> list[StagedSignal]:
        """Return approved items that have not yet been promoted."""
        q = (
            select(StagedSignal)
            .where(
                StagedSignal.status == "approved",
                StagedSignal.promoted_case_id.is_(None),
            )
            .order_by(StagedSignal.submitted_at.asc())
            .limit(limit)
        )
        return (await self.db.execute(q)).scalars().all()

    async def mark_promoted(
        self, staged_id: str, case_id: str | None, entity_id: str | None
    ) -> None:
        row = await self._get_or_404(staged_id)
        row.promoted_case_id = case_id
        row.promoted_entity_id = entity_id
        await self.db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_or_404(self, staged_id: str) -> StagedSignal:
        result = await self.db.execute(
            select(StagedSignal).where(StagedSignal.staged_id == staged_id)
        )
        row = result.scalars().first()
        if row is None:
            raise ValueError(f"staged_id '{staged_id}' not found")
        return row


def _to_dict(r: StagedSignal) -> dict:
    return {
        "staged_id": r.staged_id,
        "source_name": r.source_name,
        "source_url": r.source_url,
        "trust_level": r.trust_level,
        "canonical_name": r.canonical_name,
        "entity_type": r.entity_type,
        "detected_location": r.detected_location,
        "signal_type": r.signal_type,
        "confidence_baseline": r.confidence_baseline,
        "status": r.status,
        "auto_validated": r.auto_validated,
        "validation_notes": r.validation_notes,
        "rejection_reason": r.rejection_reason,
        "reviewed_by": r.reviewed_by,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "submitted_at": r.submitted_at.isoformat(),
        "promoted_case_id": r.promoted_case_id,
        "promoted_entity_id": r.promoted_entity_id,
    }
