import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TrustConfig(Base):
    __tablename__ = "trust_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    config_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, default="default")
    risk_medium_threshold: Mapped[float] = mapped_column(Float, default=45.0)
    risk_high_threshold: Mapped[float] = mapped_column(Float, default=65.0)
    risk_critical_threshold: Mapped[float] = mapped_column(Float, default=80.0)
    cluster_similarity_threshold: Mapped[float] = mapped_column(Float, default=0.62)
    false_positive_penalty: Mapped[float] = mapped_column(Float, default=0.1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
