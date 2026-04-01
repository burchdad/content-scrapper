"""Interpol Red Notice ingestion.

Supports two modes:

  live=True  — Fetches directly from the INTERPOL public REST API
               (ws-public.interpol.int/notices/v1/red).  Requires httpx.
               Use ``pages`` to control how many pages (20 records/page) to
               pull, and ``fetch_details`` to enrich each notice with charge
               information via a second per-record request.

  live=False — Reads a local JSON or CSV file previously saved to disk.

               Supported JSON shapes:
                 • Real Interpol API dump: {"_embedded": {"notices": [...]}}
                 • Simplified list:        [{"entity_id": "...", ...}, ...]
                 • Wrapper object:         {"notices": [...]} / {"records": [...]}
               CSV: rows with headers matching the field names documented below.

Field reference (all optional; missing fields are handled gracefully)
------------------------------------------------------------------------
entity_id          "2026/21762" or full path "/notices/v1/red/2026-21762"
forename           First name(s)
name               Family / last name
date_of_birth      "1987/12/01" or ISO "1987-12-01"
nationalities      list of ISO-3166-1-alpha-2 codes, or comma-string
country_of_birth_id  ISO alpha-2
sex_id             "M" / "F" / "U"
arrest_warrants    list of {charge, issuing_country_id, charge_translation}
charges            fallback free-text charge description
languages_spoken_ids  list or comma-string of language codes
weight             numeric (kg)
height             numeric (cm)
distinguishing_marks  free text
thumbnail          URL (informational only, not fetched)
"""
import csv
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

_API_BASE = "https://ws-public.interpol.int/notices/v1/red"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/",
    "Origin": "https://www.interpol.int",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _coerce_list(value: Any) -> list[str]:
    """Return a list of strings from a list, comma-string, or scalar."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _notice_key(entity_id: str) -> str:
    """Convert API entity_id ('2026/21762') to the URL key form ('2026-21762')."""
    return entity_id.replace("/", "-").lstrip("-")


class InterpolIngester(BaseIngester):
    """Ingest INTERPOL Red Notice records — live API or local file."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        data_file: str | None = None,
        live: bool = False,
        pages: int = 1,
        per_page: int = 20,
        fetch_details: bool = True,
    ):
        super().__init__(session)
        self.data_file = Path(data_file) if data_file else None
        self.live = live
        self.pages = max(1, pages)
        self.per_page = min(max(1, per_page), 20)  # API caps at 20
        self.fetch_details = fetch_details

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        try:
            records = await self._load_records()
        except Exception as exc:
            return {
                **self.report(),
                "skipped": True,
                "reason": str(exc),
                "source": "interpol",
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
            "records_loaded": len(records),
            "cases_created": cases_created,
            "source": "interpol",
            "mode": "live" if self.live else "file",
        }

    # ------------------------------------------------------------------
    # Record loading — live API or local file
    # ------------------------------------------------------------------

    async def _load_records(self) -> list[dict[str, Any]]:
        if self.live:
            return await self._fetch_live()
        return self._read_file()

    async def _fetch_live(self) -> list[dict[str, Any]]:
        """Pull pages from the INTERPOL public API with optional detail enrichment."""
        all_notices: list[dict[str, Any]] = []
        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
            for page in range(1, self.pages + 1):
                resp = await client.get(
                    _API_BASE,
                    params={"resultPerPage": self.per_page, "page": page},
                )
                resp.raise_for_status()
                page_data = resp.json()
                notices = page_data.get("_embedded", {}).get("notices", [])
                if not notices:
                    break
                if self.fetch_details:
                    for notice in notices:
                        detail_url = notice.get("_links", {}).get("self", {}).get("href", "")
                        if detail_url:
                            try:
                                dr = await client.get(detail_url)
                                if dr.status_code == 200:
                                    notice.update(dr.json())
                            except Exception:
                                pass  # fall back to list-only data
                all_notices.extend(notices)
        return all_notices

    def _read_file(self) -> list[dict[str, Any]]:
        if not self.data_file:
            raise ValueError("No data_file provided and live=False")
        if not self.data_file.exists():
            raise FileNotFoundError(f"file not found: {self.data_file}")

        suffix = self.data_file.suffix.lower()

        if suffix == ".json":
            raw = json.loads(self.data_file.read_text(encoding="utf-8"))
            # Real Interpol API dump: {"_embedded": {"notices": [...]}}
            if isinstance(raw, dict) and "_embedded" in raw:
                return raw["_embedded"].get("notices", [])
            if isinstance(raw, dict):
                for key in ("notices", "records", "data", "results"):
                    if key in raw and isinstance(raw[key], list):
                        return raw[key]
                raise ValueError("JSON object must contain a list under '_embedded.notices', 'notices', 'records', 'data', or 'results'")
            if isinstance(raw, list):
                return raw
            raise ValueError("JSON must be a list or object containing a list")

        if suffix == ".csv":
            with self.data_file.open("r", encoding="utf-8", newline="") as f:
                return list(csv.DictReader(f))

        raise ValueError(f"Unsupported file type '{suffix}'. Use .json or .csv")

    # ------------------------------------------------------------------
    # Record processing
    # ------------------------------------------------------------------

    async def _process_record(self, record: dict[str, Any], index: int) -> bool:
        # --- identity ---
        raw_id = str(record.get("entity_id") or record.get("notice_id") or "").strip()
        # Real API: "2026/21762"  →  key: "2026-21762"
        # Old format: "/notices/v1/red/2026-21762"  →  key: last segment
        if "/" in raw_id:
            notice_key = raw_id.replace("/", "-").lstrip("-") or f"UNKNOWN-{index:04d}"
        else:
            notice_key = raw_id or f"UNKNOWN-{index:04d}"

        forename = str(record.get("forename") or record.get("first_name") or "").strip()
        surname = str(record.get("name") or record.get("last_name") or "").strip()
        canonical_name = (
            " ".join(p for p in [forename, surname] if p) or f"Interpol Notice {notice_key}"
        )

        dob = str(record.get("date_of_birth") or "").replace("/", "-").strip()
        sex = str(record.get("sex_id") or record.get("sex") or "U").strip().upper()
        nationalities = _coerce_list(record.get("nationalities") or record.get("nationality"))
        country_of_birth = str(record.get("country_of_birth_id") or "").strip()
        languages = _coerce_list(record.get("languages_spoken_ids") or record.get("languages"))
        distinguishing_marks = str(record.get("distinguishing_marks") or "").strip()
        weight = record.get("weight")
        height = record.get("height")
        thumbnail = (
            record.get("_links", {}).get("thumbnail", {}).get("href", "")
            or str(record.get("thumbnail") or "")
        ).strip()

        # --- charges: real API uses arrest_warrants[] ---
        warrants: list[dict] = record.get("arrest_warrants") or []
        if warrants:
            charge_parts = []
            wanted_by: list[str] = []
            for w in warrants:
                c = w.get("charge_translation") or w.get("charge") or ""
                if c:
                    charge_parts.append(c.strip())
                country = w.get("issuing_country_id") or ""
                if country:
                    wanted_by.append(country.strip())
            charges = "; ".join(charge_parts)
        else:
            charges = str(record.get("charges") or record.get("charge_description") or "").strip()
            wanted_by = _coerce_list(record.get("wanted_by") or record.get("issuing_country"))

        source_url = f"https://ws-public.interpol.int/notices/v1/red/{notice_key}"

        # --- stable entity / case IDs ---
        entity_id = f"INTERPOL-ENTITY-{notice_key}"[:64]
        case_id = f"INTERPOL-CASE-{notice_key}"[:64]

        # --- deduplication ---
        existing_entity = await self.session.execute(
            select(Entity).where(Entity.entity_id == entity_id)
        )
        entity = existing_entity.scalar_one_or_none()

        if not entity:
            entity = Entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type="subject",
                confidence=0.90,
                source_count=1,
                extra_metadata={
                    "data_class": "sensitive_public",
                    "usage": "law_enforcement_reference",
                    "source": "Interpol",
                    "source_label": "interpol",
                    "notice_key": notice_key,
                    "date_of_birth": dob,
                    "sex": sex,
                    "nationalities": nationalities,
                    "country_of_birth": country_of_birth,
                    "charges": charges,
                    "wanted_by": wanted_by,
                    "languages": languages,
                    "distinguishing_marks": distinguishing_marks,
                    "weight_kg": weight,
                    "height_cm": height,
                    "thumbnail": thumbnail,
                    "source_url": source_url,
                },
            )
            self.session.add(entity)
            await self.session.flush()

        # --- signal ---
        signal = Signal(
            signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
            entity_id=entity.entity_id,
            signal_type="law_enforcement_hit",
            label="INTERPOL Red Notice",
            confidence=0.92,
            evidence=(charges or "INTERPOL Red Notice — international arrest request")[:2000],
            source_name="interpol",
            source_url=source_url,
            detected_at=datetime.now(UTC),
            raw_text_snippet=(
                f"Wanted: {canonical_name} | Charges: {charges or 'unknown'} | "
                f"Nationalities: {', '.join(nationalities) or 'unknown'} | "
                f"Wanted by: {', '.join(wanted_by) or 'unknown'}"
            )[:500],
            extra_metadata={
                "data_class": "sensitive_public",
                "usage": "law_enforcement_reference",
                    "source": "Interpol",
                    "source_label": "interpol",
                "notice_key": notice_key,
                "nationalities": nationalities,
                "charges": charges,
                "wanted_by": wanted_by,
                "arrest_warrants": warrants,
            },
        )
        self.session.add(signal)
        await self.session.flush()

        # --- case ---
        existing_case = await self.session.execute(
            select(Case).where(Case.case_id == case_id)
        )
        case = existing_case.scalar_one_or_none()

        if not case:
            nationality_str = ", ".join(nationalities) or "unknown"
            case = Case(
                case_id=case_id,
                status="under_review",
                risk_score=88.0,
                confidence_score=0.90,
                system_confidence=0.90,
                entity_ids=[entity.entity_id],
                signal_ids=[signal.signal_id],
                notes=(
                    f"INTERPOL Red Notice: {canonical_name} | "
                    f"Nationality: {nationality_str} | "
                    f"Charges: {charges or 'not disclosed'}"
                ),
                extra_metadata={
                    "data_class": "sensitive_public",
                    "usage": "law_enforcement_reference",
                    "source": "Interpol",
                    "source_label": "interpol",
                    "notice_key": notice_key,
                    "charges": charges,
                    "wanted_by": wanted_by,
                    "source_url": source_url,
                },
            )
            self.session.add(case)
            return True

        # Update existing case with new signal reference.
        if signal.signal_id not in case.signal_ids:
            case.signal_ids = [*case.signal_ids, signal.signal_id]
        if entity.entity_id not in case.entity_ids:
            case.entity_ids = [*case.entity_ids, entity.entity_id]
        return False
