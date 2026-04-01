"""NamUs ingestion for Missing, Unidentified, and Unclaimed Persons.

Supports two modes:

  live=True  - fetches directly from the public NamUs API used by the search
               page and optionally enriches each case with the public case
               detail endpoint.

  live=False - reads a local JSON or CSV export file.

The ``case_set`` parameter controls which registry is queried:
  - "MissingPersons"      (default)
  - "UnidentifiedPersons"
  - "UnclaimedPersons"
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

_BASE = "https://www.namus.gov/api/CaseSets/NamUs"

# Per-case-set configuration ------------------------------------------------
_CASE_SET_CONFIG: dict[str, dict[str, Any]] = {
    "MissingPersons": {
        "search_url": f"{_BASE}/MissingPersons/Search",
        "case_url": f"{_BASE}/MissingPersons/Cases/{{case_id}}",
        "referer": "https://www.namus.gov/MissingPersons/Search",
        "id_prefix": "MP",
        "entity_prefix": "NAMUS-MP",
        "case_prefix": "NAMUS-CASE-MP",
        "source_label": "namus_missing",
        "signal_label": "Missing Person Reference Record",
        "profile_url": "https://www.namus.gov/MissingPersons/Case#/{case_number}",
        "projections": [
            "idFormatted",
            "dateOfLastContact",
            "lastName",
            "firstName",
            "computedMissingMinAge",
            "computedMissingMaxAge",
            "cityOfLastContact",
            "countyDisplayNameOfLastContact",
            "stateDisplayNameOfLastContact",
            "gender",
            "raceEthnicity",
            "modifiedDateTime",
        ],
        "document_fragments": ["birthDate"],
    },
    "UnidentifiedPersons": {
        "search_url": f"{_BASE}/UnidentifiedPersons/Search",
        "case_url": f"{_BASE}/UnidentifiedPersons/Cases/{{case_id}}",
        "referer": "https://www.namus.gov/UnidentifiedPersons/Search",
        "id_prefix": "UP",
        "entity_prefix": "NAMUS-UP",
        "case_prefix": "NAMUS-CASE-UP",
        "source_label": "namus_unidentified",
        "signal_label": "Unidentified Person Reference Record",
        "profile_url": "https://www.namus.gov/UnidentifiedPersons/Case#/{case_number}",
        "projections": [
            "idFormatted",
            "dateFound",
            "estimatedAgeFrom",
            "estimatedAgeTo",
            "cityOfRecovery",
            "countyOfRecovery",
            "stateOfRecovery",
            "sex",
            "raceEthnicity",
            "modifiedDateTime",
        ],
        "document_fragments": [],
    },
    "UnclaimedPersons": {
        "search_url": f"{_BASE}/UnclaimedPersons/Search",
        "case_url": f"{_BASE}/UnclaimedPersons/Cases/{{case_id}}",
        "referer": "https://www.namus.gov/UnclaimedPersons/Search",
        "id_prefix": "UC",
        "entity_prefix": "NAMUS-UC",
        "case_prefix": "NAMUS-CASE-UC",
        "source_label": "namus_unclaimed",
        "signal_label": "Unclaimed Person Reference Record",
        "profile_url": "https://www.namus.gov/UnclaimedPersons/Case#/{case_number}",
        "projections": [
            "idFormatted",
            "modifiedDateTime",
        ],
        "document_fragments": [],
    },
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.namus.gov",
    "X-Requested-With": "XMLHttpRequest",
}


class NamUsIngester(BaseIngester):
    """Ingest person records from NamUs live API or local exports.

    ``case_set`` selects the registry:
        - "MissingPersons"      (default)
        - "UnidentifiedPersons"
        - "UnclaimedPersons"
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        case_set: str = "MissingPersons",
        data_file: str | None = None,
        live: bool = False,
        pages: int = 1,
        per_page: int = 25,
        fetch_details: bool = True,
        last_name: str | None = None,
        first_name: str | None = None,
        case_number: str | None = None,
        city: str | None = None,
        state: str | None = None,
    ):
        super().__init__(session)
        if case_set not in _CASE_SET_CONFIG:
            raise ValueError(f"Unknown case_set '{case_set}'. Choose from: {list(_CASE_SET_CONFIG)}")
        self._cfg = _CASE_SET_CONFIG[case_set]
        self.case_set = case_set
        self.data_file = Path(data_file) if data_file else None
        self.live = live
        self.pages = max(1, pages)
        self.per_page = max(1, min(per_page, 100))
        self.fetch_details = fetch_details
        self.last_name = (last_name or "").strip() or None
        self.first_name = (first_name or "").strip() or None
        self.case_number = (case_number or "").strip() or None
        self.city = (city or "").strip() or None
        self.state = (state or "").strip() or None

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        try:
            records = await self._load_records()
        except Exception as exc:
            return {
                **self.report(),
                "skipped": True,
                "reason": str(exc),
                "source": "namus",
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
            "source": "namus",
            "case_set": self.case_set,
            "mode": "live" if self.live else "file",
        }

    async def _load_records(self) -> list[dict[str, Any]]:
        if self.live:
            return await self._fetch_live_records()
        return self._read_file_records()

    async def _fetch_live_records(self) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        predicates = self._build_predicates()
        cfg = self._cfg
        headers = {**_HEADERS, "Referer": cfg["referer"]}

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:
            for page in range(self.pages):
                payload: dict[str, Any] = {
                    "predicates": predicates,
                    "take": self.per_page,
                    "skip": page * self.per_page,
                    "projections": cfg["projections"],
                    "orderSpecifications": [
                        {
                            "field": (
                                cfg["projections"][1]
                                if len(cfg["projections"]) > 1
                                else cfg["projections"][0]
                            ),
                            "direction": "Descending",
                        }
                    ],
                }
                if cfg["document_fragments"]:
                    payload["documentFragments"] = cfg["document_fragments"]
                response = await client.post(cfg["search_url"], json=payload)
                response.raise_for_status()
                data = response.json()
                results = data.get("results") or []
                if not results:
                    break

                if self.fetch_details:
                    enriched: list[dict[str, Any]] = []
                    for result in results:
                        case_number = result.get("namus2Number") or self._extract_case_number(result)
                        if not case_number:
                            enriched.append(result)
                            continue
                        try:
                            detail_response = await client.get(cfg["case_url"].format(case_id=case_number))
                            if detail_response.status_code == 200:
                                result = {**result, "detail": detail_response.json()}
                        except Exception:
                            pass
                        enriched.append(result)
                    results = enriched

                all_results.extend(results)

        return all_results

    def _read_file_records(self) -> list[dict[str, Any]]:
        if not self.data_file:
            raise ValueError("No data_file provided and live=False")
        if not self.data_file.exists():
            raise FileNotFoundError(f"file not found: {self.data_file}")

        if self.data_file.suffix.lower() == ".json":
            data = json.loads(self.data_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "records" in data and isinstance(data["records"], list):
                    return data["records"]
                if "results" in data and isinstance(data["results"], list):
                    return data["results"]
                raise ValueError("JSON object must include a list field named 'records' or 'results'")
            if isinstance(data, list):
                return data
            raise ValueError("JSON must be a list or object with a records/results list")

        if self.data_file.suffix.lower() == ".csv":
            with self.data_file.open("r", encoding="utf-8", newline="") as f:
                return list(csv.DictReader(f))

        raise ValueError("Unsupported file type. Use .json or .csv")

    def _build_predicates(self) -> list[dict[str, Any]]:
        predicates: list[dict[str, Any]] = []
        city_field_by_case_set = {
            "MissingPersons": "cityOfLastContact",
            "UnidentifiedPersons": "cityOfRecovery",
            "UnclaimedPersons": None,
        }
        state_field_by_case_set = {
            "MissingPersons": "stateOfLastContact",
            "UnidentifiedPersons": "stateOfRecovery",
            "UnclaimedPersons": None,
        }
        if self.case_number:
            digits = "".join(ch for ch in self.case_number if ch.isdigit())
            if digits:
                predicates.append({"field": "namus2Number", "operator": "EqualTo", "value": digits})
        if self.last_name:
            predicates.append({"field": "lastName", "operator": "Contains", "value": self.last_name})
        if self.first_name:
            predicates.append({"field": "firstName", "operator": "Contains", "value": self.first_name})
        city_field = city_field_by_case_set.get(self.case_set)
        state_field = state_field_by_case_set.get(self.case_set)
        if self.city and city_field:
            predicates.append({"field": city_field, "operator": "IsIn", "values": [self.city]})
        if self.state and state_field:
            predicates.append({"field": state_field, "operator": "IsIn", "values": [self.state]})
        return predicates

    def _extract_case_number(self, record: dict[str, Any]) -> str | None:
        case_number = record.get("namus2Number")
        if case_number:
            return str(case_number)
        formatted = str(record.get("idFormatted") or "").strip().upper()
        # Strip any known prefix (MP, UP, UC)
        for prefix in ("MP", "UP", "UC"):
            if formatted.startswith(prefix):
                return formatted[len(prefix):]
        if formatted.isdigit():
            return formatted
        link = str(record.get("link") or "")
        return link.rsplit("/", 1)[-1].lstrip("#") if link else None

    async def _process_record(self, record: dict[str, Any], index: int) -> bool:
        cfg = self._cfg
        detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}

        case_number = (
            self._extract_case_number(record)
            or str(record.get("namus_case") or record.get("case_id") or f"UNKNOWN-{index}").strip()
        )

        subject_identification = detail.get("subjectIdentification") or {}
        subject_description = detail.get("subjectDescription") or {}
        sighting = detail.get("sighting") or {}
        address = sighting.get("address") or {}
        circumstances_data = detail.get("circumstances") or {}
        primary_ethnicity = subject_description.get("primaryEthnicity") or {}
        sex_obj = subject_description.get("sex") or {}

        # Name (missing/unclaimed may have names; unidentified usually won't)
        first_name = str(
            subject_identification.get("firstName")
            or record.get("first_name")
            or record.get("firstName")
            or ""
        ).strip()
        last_name = str(
            subject_identification.get("lastName")
            or record.get("last_name")
            or record.get("lastName")
            or ""
        ).strip()
        alias = str(record.get("alias") or "").strip()

        age = (
            subject_identification.get("currentMinAge")
            or record.get("age")
            or record.get("computedMissingMinAge")
            or record.get("estimatedAgeFrom")
            or record.get("missingAgeRangeValue")
        )
        sex = str(
            sex_obj.get("localizedName")
            or sex_obj.get("name")
            or record.get("sex")
            or record.get("gender")
            or "unknown"
        ).strip()

        # Location fields differ per case set
        last_contact = str(
            sighting.get("date")
            or record.get("last_contact_date")
            or record.get("dateOfLastContact")
            or record.get("dateFound")
            or record.get("datePronounced")
            or ""
        )
        city = str(
            address.get("city")
            or record.get("last_city")
            or record.get("cityOfLastContact")
            or record.get("cityOfRecovery")
            or record.get("city")
            or ""
        )
        state_obj = address.get("state") or {}
        state = str(
            state_obj.get("displayName")
            or record.get("last_state")
            or record.get("stateDisplayNameOfLastContact")
            or record.get("stateOfRecovery")
            or record.get("stateDisplayName")
            or ""
        )
        county_obj = address.get("county") or {}
        county = str(
            county_obj.get("displayName")
            or record.get("countyDisplayNameOfLastContact")
            or record.get("countyOfRecovery")
            or record.get("county")
            or ""
        )
        circumstances = str(
            circumstances_data.get("circumstancesOfDisappearance")
            or circumstances_data.get("circumstancesOfDeath")
            or record.get("circumstances")
            or ""
        )
        race_ethnicity = str(primary_ethnicity.get("localizedName") or record.get("raceEthnicity") or "")
        source_url = str(
            record.get("source_url")
            or cfg["profile_url"].format(case_number=case_number)
        ).strip()

        case_type_label = {
            "MissingPersons": "Missing Person",
            "UnidentifiedPersons": "Unidentified Person",
            "UnclaimedPersons": "Unclaimed Person",
        }.get(self.case_set, "NamUs Case")

        canonical_name = (
            " ".join(part for part in [first_name, last_name] if part).strip()
            or f"{case_type_label} {case_number}"
        )
        entity_id = f"{cfg['entity_prefix']}-{case_number}".replace(" ", "_")[:64]
        case_id = f"{cfg['case_prefix']}-{case_number}".replace(" ", "_")[:64]

        existing = await self.session.execute(select(Entity).where(Entity.entity_id == entity_id))
        entity = existing.scalar_one_or_none()
        if not entity:
            entity = Entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type="victim",
                confidence=0.84,
                source_count=1,
                extra_metadata={
                    "data_class": "sensitive_public",
                    "usage": "reference_only",
                    "source": "NamUs",
                    "source_label": cfg["source_label"],
                    "case_set": self.case_set,
                    "namus_case": case_number,
                    "age": age,
                    "sex": sex,
                    "race_ethnicity": race_ethnicity,
                    "last_known_city": city,
                    "last_known_county": county,
                    "last_known_state": state,
                    "last_contact_date": last_contact,
                    "source_url": source_url,
                },
            )
            self.session.add(entity)
            await self.session.flush()

        signal = Signal(
            signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
            entity_id=entity.entity_id,
            signal_type="victim_interview_match",
            label=cfg["signal_label"],
            confidence=0.80,
            evidence=(circumstances or f"NamUs {self.case_set} record")[:2000],
            source_name=cfg["source_label"],
            source_url=source_url,
            detected_at=datetime.now(UTC),
            raw_text_snippet=(circumstances or canonical_name)[:500],
            extra_metadata={
                "data_class": "sensitive_public",
                "usage": "reference_only",
                "source": "NamUs",
                "source_label": cfg["source_label"],
                "case_set": self.case_set,
                "namus_case": case_number,
                "city": city,
                "county": county,
                "state": state,
                "race_ethnicity": race_ethnicity,
            },
        )
        self.session.add(signal)
        await self.session.flush()

        existing_case = await self.session.execute(select(Case).where(Case.case_id == case_id))
        case = existing_case.scalar_one_or_none()
        if not case:
            location_parts = [part for part in [city, county, state] if part]
            location = ", ".join(location_parts)
            case = Case(
                case_id=case_id,
                status="under_review",
                risk_score=72.0,
                confidence_score=0.80,
                system_confidence=0.80,
                entity_ids=[entity.entity_id],
                signal_ids=[signal.signal_id],
                notes=(
                    f"Potential correlation detected between NamUs {case_type_label.lower()} "
                    f"reference record and external signals (confidence: 0.80). "
                    f"Last known area: {location or 'unknown'}."
                ),
                extra_metadata={
                    "data_class": "sensitive_public",
                    "usage": "reference_only",
                    "source": "NamUs",
                    "source_label": cfg["source_label"],
                    "case_set": self.case_set,
                    "namus_case": case_number,
                    "source_url": source_url,
                    "alias": alias,
                    "race_ethnicity": race_ethnicity,
                },
            )
            self.session.add(case)
            return True

        if signal.signal_id not in case.signal_ids:
            case.signal_ids = [*case.signal_ids, signal.signal_id]
        if entity.entity_id not in case.entity_ids:
            case.entity_ids = [*case.entity_ids, entity.entity_id]
        return False
