from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.models.entity import Entity
from app.models.schemas import (
    AliasOut,
    EntityCorrelationResponse,
    EntityListResponse,
    EntityOut,
    EntityTimelineResponse,
    EntityEventOut,
)
from app.services.correlation_service import CorrelationService
from app.services.entity_memory_service import EntityMemoryService

router = APIRouter(prefix="/api/v1", tags=["entities"])
settings = get_settings()


def _mask_name(name: str) -> str:
    tokens = [t for t in name.split() if t]
    if not tokens:
        return "Unknown"
    if len(tokens) == 1:
        return f"{tokens[0][:1]}***"
    first = tokens[0]
    last = tokens[-1]
    return f"{first[:1]}*** {last[:1]}***"


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    entity_type: str | None = Query(default=None),
    reference_only: bool = Query(default=False),
    reference_source: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> EntityListResponse:
    """List resolved entities with pagination and optional type filter."""
    stmt = select(Entity).options(selectinload(Entity.aliases))

    if entity_type:
        stmt = stmt.where(Entity.entity_type == entity_type)

    result = await db.execute(stmt)
    entities = result.scalars().all()

    if reference_only:
        entities = [
            e
            for e in entities
            if (e.extra_metadata or {}).get("data_class") == "sensitive_public"
            and (e.extra_metadata or {}).get("usage") in {"reference_only", "law_enforcement_reference"}
        ]

        if reference_source:
            normalized_reference_source = reference_source.strip().lower()
            entities = [
                e
                for e in entities
                if str((e.extra_metadata or {}).get("source") or "").strip().lower()
                == normalized_reference_source
            ]

    total = len(entities)
    paged_entities = entities[offset : offset + limit]

    return EntityListResponse(
        entities=[_entity_out(e) for e in paged_entities],
        total=total,
        disclaimer=settings.disclaimer,
    )


@router.get("/entities/{entity_id}", response_model=EntityOut)
async def get_entity(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
) -> EntityOut:
    """Retrieve a single entity by its entity_id."""
    stmt = (
        select(Entity)
        .where(Entity.entity_id == entity_id)
        .options(selectinload(Entity.aliases))
    )
    result = await db.execute(stmt)
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _entity_out(entity)


def _entity_out(entity: Entity) -> EntityOut:
    md = entity.extra_metadata or {}
    data_class = str(md.get("data_class") or "standard")
    usage = str(md.get("usage") or "analysis")
    source_label = str(md.get("source_label") or md.get("source") or "unknown")

    is_reference_data = data_class == "sensitive_public" and usage == "reference_only"
    display_name = _mask_name(entity.canonical_name) if is_reference_data else entity.canonical_name
    badge = "Missing Person Record (Reference Data)" if is_reference_data else None

    return EntityOut(
        entity_id=entity.entity_id,
        canonical_name=entity.canonical_name,
        display_name=display_name,
        entity_type=entity.entity_type,
        confidence=entity.confidence,
        source_count=entity.source_count,
        is_pii_masked=entity.is_pii_masked or is_reference_data,
        data_class=data_class,
        usage=usage,
        source_label=source_label,
        record_badge=badge,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        aliases=[
            AliasOut(alias=a.alias, alias_type=a.alias_type, source=a.source)
            for a in entity.aliases
        ],
        disclaimer=settings.disclaimer,
    )


@router.get("/entities/{entity_id}/timeline", response_model=EntityTimelineResponse)
async def get_entity_timeline(
    entity_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> EntityTimelineResponse:
    service = EntityMemoryService(db)
    events = await service.timeline(entity_id=entity_id, limit=limit)
    return EntityTimelineResponse(
        entity_id=entity_id,
        events=[EntityEventOut.model_validate(e) for e in events],
        total=len(events),
        disclaimer=settings.disclaimer,
    )


@router.get("/entities/{entity_id}/correlations", response_model=EntityCorrelationResponse)
async def get_entity_correlations(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
) -> EntityCorrelationResponse:
    correlation = await CorrelationService(db).entity_correlation_features(entity_id)
    return EntityCorrelationResponse(
        entity_id=correlation["entity_id"],
        found=correlation["found"],
        source_diversity=correlation["source_diversity"],
        cross_source_reinforcement=correlation["cross_source_reinforcement"],
        shared_identifier_hits=correlation["shared_identifier_hits"],
        temporal_burst_24h=correlation["temporal_burst_24h"],
        event_count=correlation.get("event_count", 0),
        confidence=correlation.get("confidence", 0.0),
        interpretation=(
            "Potential correlation detected between records and external signals; "
            "this is not a legal determination."
        ),
        disclaimer=settings.disclaimer,
    )
