import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalystFeedback(Base):
    __tablename__ = "analyst_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feedback_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(String(64), ForeignKey("cases.case_id", ondelete="CASCADE"), index=True)
    analyst_id: Mapped[str] = mapped_column(String(256), index=True)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, default=False)
    corrected_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
