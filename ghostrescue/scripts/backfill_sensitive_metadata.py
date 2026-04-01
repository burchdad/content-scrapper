"""Backfill sensitive metadata and entity roles for historical records.

This script updates existing rows so older data matches current safeguards:
- NamUs: data_class=sensitive_public, source=NamUs, usage=reference_only, entity_type=victim
- Interpol: data_class=sensitive_public, source=Interpol, usage=law_enforcement_reference, entity_type=subject
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal


def _merge_metadata(base: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(updates)
    return merged


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    counts = {
        "entity_namus": 0,
        "entity_interpol": 0,
        "signal_namus": 0,
        "signal_interpol": 0,
        "case_namus": 0,
        "case_interpol": 0,
    }

    async with session_factory() as session:
        await _backfill_entities(session, counts)
        await _backfill_signals(session, counts)
        await _backfill_cases(session, counts)
        await session.commit()

    await engine.dispose()

    print("Backfill complete:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


async def _backfill_entities(session: AsyncSession, counts: dict[str, int]) -> None:
    rows = (await session.execute(select(Entity))).scalars().all()
    for entity in rows:
        md = entity.extra_metadata or {}

        if entity.entity_id.startswith("NAMUS-"):
            source_label = md.get("source_label") or md.get("source") or "namus"
            entity.entity_type = "victim"
            entity.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "NamUs",
                    "source_label": source_label,
                    "usage": "reference_only",
                },
            )
            counts["entity_namus"] += 1
            continue

        if entity.entity_id.startswith("INTERPOL-"):
            source_label = md.get("source_label") or "interpol"
            entity.entity_type = "subject"
            entity.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "Interpol",
                    "source_label": source_label,
                    "usage": "law_enforcement_reference",
                },
            )
            counts["entity_interpol"] += 1


async def _backfill_signals(session: AsyncSession, counts: dict[str, int]) -> None:
    rows = (await session.execute(select(Signal))).scalars().all()
    for signal in rows:
        md = signal.extra_metadata or {}
        source_name = (signal.source_name or "").lower()

        if signal.entity_id and signal.entity_id.startswith("NAMUS-") or source_name.startswith("namus"):
            source_label = md.get("source_label") or signal.source_name or md.get("source") or "namus"
            signal.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "NamUs",
                    "source_label": source_label,
                    "usage": "reference_only",
                },
            )
            counts["signal_namus"] += 1
            continue

        if signal.entity_id and signal.entity_id.startswith("INTERPOL-") or source_name.startswith("interpol"):
            source_label = md.get("source_label") or signal.source_name or "interpol"
            signal.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "Interpol",
                    "source_label": source_label,
                    "usage": "law_enforcement_reference",
                },
            )
            counts["signal_interpol"] += 1


async def _backfill_cases(session: AsyncSession, counts: dict[str, int]) -> None:
    rows = (await session.execute(select(Case))).scalars().all()
    for case in rows:
        md = case.extra_metadata or {}

        if case.case_id.startswith("NAMUS-CASE-"):
            source_label = md.get("source_label") or md.get("source") or "namus"
            case.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "NamUs",
                    "source_label": source_label,
                    "usage": "reference_only",
                },
            )
            counts["case_namus"] += 1
            continue

        if case.case_id.startswith("INTERPOL-CASE-"):
            source_label = md.get("source_label") or "interpol"
            case.extra_metadata = _merge_metadata(
                md,
                {
                    "data_class": "sensitive_public",
                    "source": "Interpol",
                    "source_label": source_label,
                    "usage": "law_enforcement_reference",
                },
            )
            counts["case_interpol"] += 1


if __name__ == "__main__":
    asyncio.run(main())
