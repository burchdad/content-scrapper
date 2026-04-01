"""StagedSignal — holding area for intelligence from unvalidated or scraper sources.

Lifecycle:  pending → (approved | rejected) → (if approved) promoted to main ingest pipeline

An analyst or the auto-validator reviews each staged item before it is allowed
to influence GhostRescue's corroboration scoring.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StagedSignal(Base):
    __tablename__ = "staged_signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    staged_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
        default=lambda: f"STAGED-{uuid.uuid4().hex[:12].upper()}"
    )

    # --- Source identification ---
    source_name: Mapped[str] = mapped_column(String(256), index=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    trust_level: Mapped[str] = mapped_column(String(64), default="unvalidated_osint")

    # --- Raw payload from scraper ---
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Normalized fields (populated by staging validator) ---
    canonical_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="person")
    detected_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence_baseline: Mapped[float] = mapped_column(default=0.0)

    # --- Review state ---
    # Status: pending → approved | rejected
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    auto_validated: Mapped[bool] = mapped_column(default=False)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Reviewer ---
    reviewed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Timestamps ---
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # --- Post-approval linkage ---
    promoted_case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promoted_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
