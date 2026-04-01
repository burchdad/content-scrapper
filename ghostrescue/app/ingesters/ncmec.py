"""NCMEC missing child public poster search ingester."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingesters.base import BaseIngester
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal

_NCMEC_API = "https://api.missingkids.org/missingkids/servlet/JSONDataServlet"


class NCMECIngester(BaseIngester):
    """Ingest missing-child leads from NCMEC public poster search."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        data_file: str | None = None,
        live: bool = True,
        pages: int = 1,
        search: str = "",
    ) -> None:
        super().__init__(session)
        self.data_file = Path(data_file) if data_file else None
        self.live = live
        self.pages = max(1, min(pages, 50))
        self.search = (search or "").strip()

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        try:
            records = await self._load_records()
        except Exception as exc:
            return {
                **self.report(),
                "skipped": True,
                "reason": str(exc),
                "source": "ncmec",
            }

        cases_created = 0
        for idx, record in enumerate(records, start=1):
            try:
                created = await self._process_record(record, idx)
                if created:
                    cases_created += 1
                    self.imported_count += 1
            except Exception:
                self.error_count += 1

        await self.session.commit()

        return {
            **self.report(),
            "source": "ncmec",
            "records_loaded": len(records),
            "cases_created": cases_created,
            "mode": "live" if self.live else "file",
            "search": self.search,
            "api_endpoint": _NCMEC_API if self.live else None,
        }

    async def _load_records(self) -> list[dict[str, Any]]:
        if self.live:
            return await self._fetch_live()
        return self._read_file()

    async def _fetch_live(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for page in range(1, self.pages + 1):
                params = {
                    "action": "publicSearch",
                    "search": self.search,
                    "goToPage": str(page),
                }
                response = await client.get(_NCMEC_API, params=params)
                response.raise_for_status()

                payload = response.json()
                persons = payload.get("persons") or []
                if not isinstance(persons, list) or not persons:
                    break
                rows.extend(item for item in persons if isinstance(item, dict))

                total_pages = int(payload.get("totalPages") or 0)
                if total_pages and page >= total_pages:
                    break

        return rows

    def _read_file(self) -> list[dict[str, Any]]:
        if not self.data_file:
            raise ValueError("No data_file provided and live=False")
        if not self.data_file.exists():
            raise FileNotFoundError(f"file not found: {self.data_file}")

        suffix = self.data_file.suffix.lower()
        if suffix != ".json":
            raise ValueError("NCMEC data_file must be a .json file")

        raw = json.loads(self.data_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("persons"), list):
                return [item for item in raw.get("persons") or [] if isinstance(item, dict)]
            if isinstance(raw.get("records"), list):
                return [item for item in raw.get("records") or [] if isinstance(item, dict)]
            raise ValueError("JSON object must include 'persons' or 'records' list")
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        raise ValueError("JSON must be a list or object containing a list")

    async def _process_record(self, record: dict[str, Any], index: int) -> bool:
        case_number = str(record.get("caseNumber") or "").strip() or f"UNKNOWN-{index:05d}"
        name = " ".join(
            p for p in [
                str(record.get("firstName") or "").strip(),
                str(record.get("middleName") or "").strip(),
                str(record.get("lastName") or "").strip(),
            ]
            if p
        )
        canonical_name = name or f"NCMEC Case {case_number}"

        entity_id = f"NCMEC-ENTITY-{case_number}"[:64]
        case_id = f"NCMEC-CASE-{case_number}"[:64]

        existing_case = await self.session.execute(select(Case).where(Case.case_id == case_id))
        if existing_case.scalar_one_or_none():
            return False

        missing_city = str(record.get("missingCity") or "").strip()
        missing_state = str(record.get("missingState") or "").strip()
        missing_country = str(record.get("missingCountry") or "").strip()
        missing_date = str(record.get("missingDate") or "").strip()
        race = str(record.get("race") or "").strip()
        case_type = str(record.get("caseType") or "").strip()
        age = str(record.get("age") or "").strip()
        image_url = str(record.get("imageUrl") or record.get("thumbnailUrl") or "").strip()
        if image_url.startswith("/"):
            image_url = f"https://api.missingkids.org{image_url}"

        source_url = f"https://www.missingkids.org/gethelpnow/search/poster-search-results?caseNumber={case_number}"
        detected_at = self._parse_missing_date(missing_date)

        existing_entity = await self.session.execute(select(Entity).where(Entity.entity_id == entity_id))
        entity = existing_entity.scalar_one_or_none()
        if not entity:
            entity = Entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type="victim",
                confidence=0.82,
                source_count=1,
                extra_metadata={
                    "data_class": "sensitive_public",
                    "usage": "reference_only",
                    "source": "NCMEC",
                    "source_label": "ncmec",
                    "case_number": case_number,
                    "missing_city": missing_city,
                    "missing_state": missing_state,
                    "missing_country": missing_country,
                    "missing_date": missing_date,
                    "race": race,
                    "case_type": case_type,
                    "age": age,
                    "image_url": image_url,
                    "source_url": source_url,
                },
            )
            self.session.add(entity)
            await self.session.flush()

        signal = Signal(
            signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
            entity_id=entity.entity_id,
            signal_type="victim_interview_match",
            label="NCMEC Missing Child Record",
            confidence=0.80,
            evidence=(
                f"NCMEC public poster record for {canonical_name}. "
                f"Missing from {', '.join(p for p in [missing_city, missing_state, missing_country] if p) or 'unknown'}"
            )[:2000],
            source_name="ncmec",
            source_url=source_url,
            detected_at=detected_at,
            raw_text_snippet=(f"Case {case_number} | Age: {age or 'unknown'} | Race: {race or 'unknown'}")[:500],
            extra_metadata={
                "data_class": "sensitive_public",
                "usage": "reference_only",
                "source": "NCMEC",
                "source_label": "ncmec",
                "case_number": case_number,
                "missing_city": missing_city,
                "missing_state": missing_state,
                "missing_country": missing_country,
                "missing_date": missing_date,
                "race": race,
                "case_type": case_type,
                "age": age,
                "image_url": image_url,
            },
        )
        self.session.add(signal)
        await self.session.flush()

        case = Case(
            case_id=case_id,
            status="under_review",
            risk_score=68.0,
            confidence_score=0.80,
            system_confidence=0.80,
            entity_ids=[entity.entity_id],
            signal_ids=[signal.signal_id],
            notes=(
                f"NCMEC missing child reference record for {canonical_name}. "
                f"Case: {case_number}. Location: {', '.join(p for p in [missing_city, missing_state, missing_country] if p) or 'unknown'}."
            ),
            extra_metadata={
                "data_class": "sensitive_public",
                "usage": "reference_only",
                "source": "NCMEC",
                "source_label": "ncmec",
                "case_number": case_number,
                "missing_city": missing_city,
                "missing_state": missing_state,
                "missing_country": missing_country,
                "missing_date": missing_date,
                "race": race,
                "case_type": case_type,
                "age": age,
                "image_url": image_url,
                "source_url": source_url,
            },
        )
        self.session.add(case)
        return True

    def _parse_missing_date(self, value: str) -> datetime:
        value = (value or "").strip()
        if not value:
            return datetime.now(UTC)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        try:
            if value.endswith("Z"):
                value = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            return datetime.now(UTC)
