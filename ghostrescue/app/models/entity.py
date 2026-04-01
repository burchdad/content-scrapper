import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(512), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="person")  # person, location, organization, vehicle
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    is_pii_masked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    audit_log: Mapped[list] = mapped_column(JSON, default=list)

    aliases: Mapped[list["EntityAlias"]] = relationship(
        "EntityAlias", back_populates="entity", cascade="all, delete-orphan"
    )
    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="entity")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("entities.entity_id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(512), index=True)
    alias_type: Mapped[str] = mapped_column(String(64), default="name")  # name, nickname, username, phone, id_number
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    entity: Mapped["Entity"] = relationship("Entity", back_populates="aliases")


class EntityMergeLog(Base):
    __tablename__ = "entity_merge_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_entity_id: Mapped[str] = mapped_column(String(64), index=True)
    target_entity_id: Mapped[str] = mapped_column(String(64), index=True)
    merge_score: Mapped[float] = mapped_column(Float)
    merge_reason: Mapped[str] = mapped_column(Text)
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    merged_by: Mapped[str] = mapped_column(String(256), default="system")
