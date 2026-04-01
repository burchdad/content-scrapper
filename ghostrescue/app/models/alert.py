import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.case_id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(32), default="medium")  # low, medium, high, critical
    message: Mapped[str] = mapped_column(Text)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    case: Mapped["Case"] = relationship("Case", back_populates="alerts")
