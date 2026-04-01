from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entity import Entity, EntityAlias
from app.models.entity_event import EntityEvent


class CorrelationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def entity_correlation_features(self, entity_id: str) -> dict:
        entity_stmt = (
            select(Entity)
            .where(Entity.entity_id == entity_id)
            .options(selectinload(Entity.aliases))
        )
        entity_res = await self.db.execute(entity_stmt)
        entity = entity_res.scalar_one_or_none()
        if not entity:
            return {
                "entity_id": entity_id,
                "found": False,
                "source_diversity": 0,
                "cross_source_reinforcement": 0.0,
                "shared_identifier_hits": 0,
                "temporal_burst_24h": 0,
                "confidence": 0.0,
            }

        events_stmt = select(EntityEvent).where(EntityEvent.entity_id == entity_id)
        events_res = await self.db.execute(events_stmt)
        events = events_res.scalars().all()

        source_names = [e.source_name for e in events if e.source_name]
        source_diversity = len(set(source_names))

        alias_tokens = {a.alias.strip().lower() for a in entity.aliases if a.alias.strip()}
        shared_identifier_hits = 0
        if alias_tokens:
            alias_stmt = select(EntityAlias).where(EntityAlias.entity_id != entity_id)
            alias_res = await self.db.execute(alias_stmt)
            all_aliases = alias_res.scalars().all()
            shared_identifier_hits = sum(1 for a in all_aliases if a.alias.strip().lower() in alias_tokens)

        hourly_counts = Counter(e.event_timestamp.replace(minute=0, second=0, microsecond=0) for e in events)
        temporal_burst_24h = max(hourly_counts.values()) if hourly_counts else 0

        cross_source_reinforcement = round(
            min(1.0, (source_diversity * 0.2) + (shared_identifier_hits * 0.05) + (temporal_burst_24h * 0.05)),
            3,
        )

        confidence = round(min(1.0, 0.35 + cross_source_reinforcement * 0.65), 3)
        return {
            "entity_id": entity_id,
            "found": True,
            "source_diversity": source_diversity,
            "cross_source_reinforcement": cross_source_reinforcement,
            "shared_identifier_hits": shared_identifier_hits,
            "temporal_burst_24h": temporal_burst_24h,
            "event_count": len(events),
            "confidence": confidence,
        }
