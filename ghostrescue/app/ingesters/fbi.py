"""FBI Most Wanted ingester.

Fetches records from the public FBI Wanted API (no API key required).

All records originate from the official FBI public website:
  https://www.fbi.gov/wanted

API endpoint:
  https://api.fbi.gov/wanted/v1/list

Supported lists (filtered by path prefix in the API response):
  kidnap            - Kidnappings & Missing Persons
  parental_kidnap   - Parental Kidnappings
  vicap_missing     - ViCAP Missing Persons
  vicap_homicide    - ViCAP Homicides & Sexual Assaults
  topten            - Ten Most Wanted Fugitives
  fugitives         - Fugitives
  criminal_enterprise - Criminal Enterprise Investigations
  murders           - Violent Crime / Murders
  terrorism         - Terrorism
  lea               - Law Enforcement Assistance
  seeking_info      - Seeking Information

Default ingestion targets: kidnap, parental_kidnap, vicap_missing, topten,
fugitives, criminal_enterprise.
"""

import re
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingesters.base import BaseIngester
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal

_FBI_API = "https://api.fbi.gov/wanted/v1/list"

# Maps path prefix → per-list metadata
_LIST_CONFIG: dict[str, dict[str, str]] = {
    "/wanted/kidnap/": {
        "signal_label": "FBI Kidnap/Missing Person",
        "entity_type": "victim",
        "list_name": "kidnap",
    },
    "/wanted/parental-kidnap/": {
        "signal_label": "FBI Parental Kidnapping",
        "entity_type": "victim",
        "list_name": "parental_kidnap",
    },
    "/wanted/vicap/missing-persons/": {
        "signal_label": "FBI ViCAP Missing Person",
        "entity_type": "victim",
        "list_name": "vicap_missing",
    },
    "/wanted/vicap/homicides-and-sexual-assaults/": {
        "signal_label": "FBI ViCAP Homicide/Sexual Assault",
        "entity_type": "victim",
        "list_name": "vicap_homicide",
    },
    "/wanted/topten/": {
        "signal_label": "FBI Ten Most Wanted Fugitive",
        "entity_type": "subject",
        "list_name": "topten",
    },
    "/wanted/fugitives/": {
        "signal_label": "FBI Fugitive",
        "entity_type": "subject",
        "list_name": "fugitives",
    },
    "/wanted/cei/": {
        "signal_label": "FBI Criminal Enterprise Fugitive",
        "entity_type": "subject",
        "list_name": "criminal_enterprise",
    },
    "/wanted/murders/": {
        "signal_label": "FBI Murder Suspect",
        "entity_type": "subject",
        "list_name": "murders",
    },
    "/wanted/terrorism/": {
        "signal_label": "FBI Terrorism Suspect",
        "entity_type": "subject",
        "list_name": "terrorism",
    },
    "/wanted/law-enforcement-assistance/": {
        "signal_label": "FBI Law Enforcement Assistance",
        "entity_type": "subject",
        "list_name": "lea",
    },
    "/wanted/seeking-info/": {
        "signal_label": "FBI Seeking Information",
        "entity_type": "subject",
        "list_name": "seeking_info",
    },
}

# Default lists for GhostRescue mission alignment
_DEFAULT_LISTS: set[str] = {
    "kidnap",
    "parental_kidnap",
    "vicap_missing",
    "topten",
    "fugitives",
    "criminal_enterprise",
}

ALL_LIST_NAMES: set[str] = {cfg["list_name"] for cfg in _LIST_CONFIG.values()}


class _HtmlStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    s = _HtmlStripper()
    s.feed(raw)
    return re.sub(r"\s+", " ", s.get_text()).strip()


def _category_config(path: str) -> dict[str, str] | None:
    for prefix, cfg in _LIST_CONFIG.items():
        if path.startswith(prefix):
            return cfg
    return None


def _detect_signal_type(subjects: list[str], description: str, list_name: str) -> str:
    combined = " ".join(subjects + [description]).lower()
    if any(k in combined for k in ["trafficking", "smuggling", "exploitation"]):
        return "trafficking_indicator"
    if any(k in combined for k in ["kidnap", "missing", "abduction", "parental"]):
        return "missing_person"
    if any(k in combined for k in ["murder", "homicide", "assault", "rape", "sexual"]):
        return "violent_crime"
    if any(k in combined for k in ["terrorism", "terror"]):
        return "terrorism"
    if any(k in combined for k in ["fraud", "money laundering", "wire fraud", "embezzle"]):
        return "financial_crime"
    if any(k in combined for k in ["drugs", "narcotics", "cocaine", "heroin", "fentanyl"]):
        return "drug_trafficking"
    if any(k in combined for k in ["fugitive", "warrant", "arrest"]):
        return "fugitive"
    return "law_enforcement_reference"


def _compute_risk(warning: str, reward_max: int | float, subjects: list[str]) -> float:
    score = 40.0
    if warning and "ARMED AND DANGEROUS" in warning.upper():
        score += 30.0
    if reward_max:
        if reward_max >= 1_000_000:
            score += 20.0
        elif reward_max >= 100_000:
            score += 15.0
        elif reward_max >= 10_000:
            score += 8.0
    subjects_lower = [s.lower() for s in subjects]
    if any("terrorism" in s for s in subjects_lower):
        score += 15.0
    if any("ten most wanted" in s for s in subjects_lower):
        score += 10.0
    return min(score, 99.0)


class FBIIngester(BaseIngester):
    """Ingest records from the public FBI Most Wanted API.

    No API key required. Data is sourced from the official FBI public website.

    ``lists``    — which list names to include (default: _DEFAULT_LISTS).
    ``pages``    — how many API pages to fetch (50 records/page, max 20 pages).
    ``per_page`` — records per page request (max 50).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        lists: list[str] | None = None,
        pages: int = 10,
        per_page: int = 50,
    ) -> None:
        super().__init__(session)
        if lists:
            invalid = set(lists) - ALL_LIST_NAMES
            if invalid:
                raise ValueError(f"Unknown FBI list names: {invalid}. Valid: {ALL_LIST_NAMES}")
            self.target_lists: set[str] = set(lists)
        else:
            self.target_lists = set(_DEFAULT_LISTS)
        self.pages = max(1, min(pages, 20))
        self.per_page = max(1, min(per_page, 50))

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        try:
            matched, total_fetched = await self._fetch_records()
        except Exception as exc:
            return {
                **self.report(),
                "skipped": True,
                "reason": str(exc),
                "source": "fbi_wanted",
            }

        cases_created = 0
        for record in matched:
            try:
                created = await self._process_record(record)
                if created:
                    cases_created += 1
                    self.imported_count += 1
            except Exception:
                self.error_count += 1

        await self.session.commit()

        return {
            **self.report(),
            "records_fetched": total_fetched,
            "records_matched": len(matched),
            "cases_created": cases_created,
            "source": "fbi_wanted",
            "lists": sorted(self.target_lists),
        }

    async def _fetch_records(self) -> tuple[list[dict], int]:
        matched: list[dict] = []
        total_fetched = 0

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for page in range(1, self.pages + 1):
                params = {"pageSize": self.per_page, "page": page}
                try:
                    resp = await client.get(_FBI_API, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    print(f"  ⚠️  FBI API error (page {page}): {exc}")
                    break

                items = data.get("items") or []
                if not items:
                    break

                total_fetched += len(items)

                for item in items:
                    path = item.get("path") or ""
                    cfg = _category_config(path)
                    if cfg and cfg["list_name"] in self.target_lists:
                        matched.append({**item, "_cfg": cfg})

                # Stop when all available records have been fetched
                if total_fetched >= (data.get("total") or 0):
                    break

        return matched, total_fetched

    async def _process_record(self, record: dict) -> bool:
        cfg: dict = record["_cfg"]
        uid = record.get("uid") or str(uuid.uuid4())
        title = (record.get("title") or "").strip()
        path = record.get("path") or ""
        fbi_url = record.get("url") or f"https://www.fbi.gov{path}"

        entity_id = f"FBI-{uid}"[:64]
        case_id = f"FBI-CASE-{uid}"[:64]
        signal_id = f"FBI-SIG-{uid}"[:64]

        # Skip already-processed records
        existing = await self.session.execute(
            select(Entity).where(Entity.entity_id == entity_id)
        )
        if existing.scalar_one_or_none():
            return False

        # Physical / biographical fields
        aliases: list[str] = record.get("aliases") or []
        sex: str = record.get("sex") or ""
        race: str = record.get("race_raw") or record.get("race") or ""
        hair: str = record.get("hair_raw") or record.get("hair") or ""
        eyes: str = record.get("eyes_raw") or record.get("eyes") or ""
        height_min = record.get("height_min")
        height_max = record.get("height_max")
        weight: str = record.get("weight") or ""
        dob_list: list[str] = record.get("dates_of_birth_used") or []
        nationality: str = record.get("nationality") or ""
        place_of_birth: str = record.get("place_of_birth") or ""
        scars: str = record.get("scars_and_marks") or ""
        languages: list[str] = record.get("languages") or []
        subjects: list[str] = record.get("subjects") or []
        field_offices: list[str] = record.get("field_offices") or []
        reward_text: str = record.get("reward_text") or ""
        reward_max: float = record.get("reward_max") or 0
        warning: str = record.get("warning_message") or ""
        poster_cls: str = record.get("poster_classification") or ""
        description: str = record.get("description") or ""
        caution_text = _strip_html(record.get("caution"))
        details_text = _strip_html(record.get("details"))
        publication: str = record.get("publication") or ""
        modified: str = record.get("modified") or ""

        images: list[dict] = record.get("images") or []
        image_url: str | None = images[0].get("large") if images else None

        # Victims: poster_classification=="missing"; everything else is a subject
        entity_type = "victim" if poster_cls == "missing" else cfg["entity_type"]
        usage = "reference_only" if entity_type == "victim" else "law_enforcement_reference"

        # Title comes as ALL CAPS from FBI — convert to title case
        canonical_name = title.title() if title else f"FBI Record {uid[:8]}"

        # ── Entity ──────────────────────────────────────────────────────────
        entity = Entity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            confidence=0.95,
            source_count=1,
            extra_metadata={
                "data_class": "sensitive_public",
                "usage": usage,
                "source": "FBI",
                "source_label": "FBI Most Wanted",
                    "entity_id": entity_id,
                "fbi_uid": uid,
                "fbi_url": fbi_url,
                "poster_classification": poster_cls,
                "aliases": aliases,
                "sex": sex,
                "race": race,
                "hair": hair,
                "eyes": eyes,
                "height_min_in": height_min,
                "height_max_in": height_max,
                "weight": weight,
                "dates_of_birth": dob_list,
                "nationality": nationality,
                "place_of_birth": place_of_birth,
                "scars_and_marks": scars,
                "languages": languages,
                "subjects": subjects,
                "field_offices": field_offices,
                "warning_message": warning,
                "reward_text": reward_text,
                "reward_max": reward_max,
                "image_url": image_url,
                "fbi_publication": publication,
                "fbi_modified": modified,
                "list_name": cfg["list_name"],
            },
        )
        self.session.add(entity)

        # ── Signal ───────────────────────────────────────────────────────────
        evidence_parts = [p for p in [
            description,
            caution_text[:500] if caution_text else "",
            details_text[:300] if details_text else "",
            f"WARNING: {warning}" if warning else "",
            f"Reward: ${reward_max:,.0f}" if reward_max and reward_max > 0 else "",
        ] if p]
        evidence = " | ".join(evidence_parts)[:2000]

        signal_type = _detect_signal_type(subjects, description, cfg["list_name"])

        signal = Signal(
            signal_id=signal_id,
            signal_type=signal_type,
            label=cfg["signal_label"],
            confidence=0.95,
            evidence=evidence,
            source_name="FBI Most Wanted",
            source_url=fbi_url,
                entity_id=entity_id,
            extra_metadata={
                "data_class": "sensitive_public",
                "source": "FBI",
                "usage": usage,
                "fbi_uid": uid,
                "subjects": subjects,
                "field_offices": field_offices,
                "list_name": cfg["list_name"],
            },
        )
        self.session.add(signal)

        # ── Case ─────────────────────────────────────────────────────────────
        location_parts = [p for p in [
            f"Born: {place_of_birth}" if place_of_birth else "",
            f"FBI Field Office(s): {', '.join(field_offices)}" if field_offices else "",
        ] if p]
        location_note = "; ".join(location_parts)

        categories_str = ", ".join(subjects) if subjects else cfg["signal_label"]
        case_notes = (
            f"FBI Most Wanted record for {canonical_name}. "
            f"Category: {categories_str}. "
            + (f"{description}. " if description else "")
            + (f"{location_note}. " if location_note else "")
            + (f"Published: {publication[:10] if publication else 'unknown'}.")
        )

        case = Case(
            case_id=case_id,
            status="open",
            risk_score=_compute_risk(warning, reward_max, subjects),
            entity_ids=[entity_id],
            signal_ids=[signal_id],
            notes=case_notes[:1000],
            extra_metadata={
                "data_class": "sensitive_public",
                "source": "FBI",
                "usage": usage,
                "interpretation": (
                    "This is an official FBI public reference record. "
                    "This is not a legal determination and requires human review before any action."
                ),
            },
        )
        self.session.add(case)
        return True
