import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Status lifecycle: open → under_review → escalated → submitted → closed
    status: Mapped[str] = mapped_column(String(64), default="open")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    system_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    signal_ids: Mapped[list] = mapped_column(JSON, default=list)
    assigned_analyst: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclaimer: Mapped[str] = mapped_column(
        Text,
        default="Outputs are intelligence leads, not verified conclusions.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="case", cascade="all, delete-orphan")
