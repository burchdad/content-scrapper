import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.entity import Entity, EntityAlias, EntityMergeLog
from app.models.schemas import EntityIngestPayload, EntityResolveResult
from app.services.entity_resolution.fuzzy_matcher import FuzzyMatcher
from app.services.entity_resolution.merger import EntityMerger

logger = get_logger(__name__)
settings = get_settings()


class EntityResolver:
    """
    Orchestrates entity resolution pipeline:

    1. Normalize the incoming canonical name
    2. Load all existing entities + aliases from the DB
    3. Fuzzy-match against candidates
    4a. score >= merge_threshold  → merge source into existing entity
    4b. score >= match_threshold  → link new aliases to existing entity
    4c. no match                  → create a new entity
    5. Persist changes and return resolve result with full audit trail

    All outputs carry the compliance disclaimer.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.matcher = FuzzyMatcher(threshold=settings.entity_match_threshold)
        self.merger = EntityMerger()

    async def resolve(self, payload: EntityIngestPayload) -> EntityResolveResult:
        normalized_name = self._normalize(payload.canonical_name)
        candidates = await self._load_candidates()
        matches = self.matcher.match(normalized_name, candidates)

        if matches and matches[0].score >= settings.entity_match_threshold:
            best = matches[0]
            logger.info(
                "Entity %r matched → %s (score=%.1f, strategy=%s)",
                normalized_name,
                best.entity_id,
                best.score,
                best.match_strategy,
            )

            if best.score >= settings.entity_merge_threshold:
                entity = await self._merge_into(
                    existing_entity_id=best.entity_id,
                    payload=payload,
                    merge_score=best.score,
                )
                action = "merged"
            else:
                entity = await self._link_aliases(
                    existing_entity_id=best.entity_id,
                    payload=payload,
                )
                action = "linked"

            return EntityResolveResult(
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                action=action,
                match_score=best.score,
                match_strategy=best.match_strategy,
                matched_alias=best.matched_alias,
                disclaimer=settings.disclaimer,
            )

        # No match — create new entity
        entity = await self._create_entity(payload)
        logger.info("New entity created: %s (%r)", entity.entity_id, entity.canonical_name)
        return EntityResolveResult(
            entity_id=entity.entity_id,
            canonical_name=entity.canonical_name,
            action="created",
            match_score=None,
            match_strategy=None,
            matched_alias=None,
            disclaimer=settings.disclaimer,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_candidates(self) -> list[tuple[str, str, list[str]]]:
        stmt = select(Entity).options(selectinload(Entity.aliases))
        result = await self.db.execute(stmt)
        entities = result.scalars().all()
        return [(e.entity_id, e.canonical_name, [a.alias for a in e.aliases]) for e in entities]

    async def _create_entity(self, payload: EntityIngestPayload) -> Entity:
        entity_id = f"entity-{uuid.uuid4().hex[:12]}"
        entity = Entity(
            entity_id=entity_id,
            canonical_name=self._normalize(payload.canonical_name),
            entity_type=payload.entity_type or "person",
            confidence=1.0,
            source_count=1,
            extra_metadata=payload.extra_metadata or {},
            audit_log=[
                {
                    "event": "entity_created",
                    "source": payload.source_name,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        )

        seen: set[str] = set()
        for alias_str in payload.aliases:
            norm = alias_str.strip().lower()
            if norm and norm not in seen:
                entity.aliases.append(
                    EntityAlias(
                        entity_id=entity_id,
                        alias=alias_str.strip(),
                        alias_type="name",
                        source=payload.source_name,
                    )
                )
                seen.add(norm)

        self.db.add(entity)
        await self.db.commit()
        await self.db.refresh(entity)
        return entity

    async def _merge_into(
        self,
        existing_entity_id: str,
        payload: EntityIngestPayload,
        merge_score: float,
    ) -> Entity:
        stmt = (
            select(Entity)
            .where(Entity.entity_id == existing_entity_id)
            .options(selectinload(Entity.aliases))
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if not existing:
            # Entity disappeared between candidate load and merge — safe fallback
            return await self._create_entity(payload)

        # Build a transient source entity for the merger to absorb
        incoming = Entity(
            entity_id=f"temp-{uuid.uuid4().hex}",
            canonical_name=payload.canonical_name,
            entity_type=payload.entity_type or "person",
            source_count=1,
            aliases=[
                EntityAlias(
                    entity_id="temp",
                    alias=a.strip(),
                    alias_type="name",
                    source=payload.source_name,
                )
                for a in payload.aliases
                if a.strip()
            ],
        )

        updated, merge_log = self.merger.merge(
            source=incoming,
            target=existing,
            merge_score=merge_score,
            merge_reason=f"fuzzy_name_match score={merge_score:.1f}",
        )
        self.db.add(merge_log)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def _link_aliases(self, existing_entity_id: str, payload: EntityIngestPayload) -> Entity:
        """Mid-confidence match: add incoming name as alias without full merge."""
        stmt = (
            select(Entity)
            .where(Entity.entity_id == existing_entity_id)
            .options(selectinload(Entity.aliases))
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if not existing:
            return await self._create_entity(payload)

        existing_alias_set = {a.alias.lower() for a in existing.aliases}
        for alias_str in [payload.canonical_name, *payload.aliases]:
            norm = alias_str.strip().lower()
            if norm and norm not in existing_alias_set:
                existing.aliases.append(
                    EntityAlias(
                        entity_id=existing.entity_id,
                        alias=alias_str.strip(),
                        alias_type="name",
                        source=payload.source_name,
                    )
                )
                existing_alias_set.add(norm)

        existing.source_count += 1
        existing.updated_at = datetime.now(UTC)
        existing.audit_log = list(existing.audit_log or []) + [
            {
                "event": "alias_linked",
                "alias": payload.canonical_name,
                "source": payload.source_name,
                "linked_at": datetime.now(UTC).isoformat(),
            }
        ]
        await self.db.commit()
        await self.db.refresh(existing)
        return existing

    @staticmethod
    def _normalize(name: str) -> str:
        return " ".join(name.strip().split())
