import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity_event import EntityEvent


class EntityMemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_event(
        self,
        entity_id: str,
        event_type: str,
        summary: str,
        source_name: str | None = None,
        source_url: str | None = None,
        location: str | None = None,
        metadata: dict | None = None,
    ) -> EntityEvent:
        event = EntityEvent(
            event_id=f"event-{uuid.uuid4().hex[:12]}",
            entity_id=entity_id,
            event_type=event_type,
            source_name=source_name,
            source_url=source_url,
            location=location,
            summary=summary,
            event_timestamp=datetime.now(UTC),
            event_metadata=metadata or {},
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def timeline(self, entity_id: str, limit: int = 100) -> list[EntityEvent]:
        stmt = (
            select(EntityEvent)
            .where(EntityEvent.entity_id == entity_id)
            .order_by(EntityEvent.event_timestamp.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
