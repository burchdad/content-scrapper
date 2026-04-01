import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    signal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("entities.entity_id", ondelete="SET NULL"), nullable=True, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(256))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[str] = mapped_column(Text)
    raw_text_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    trust_level: Mapped[str] = mapped_column(String(64), default="unvalidated_osint")
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    entity: Mapped["Entity"] = relationship("Entity", back_populates="signals")
