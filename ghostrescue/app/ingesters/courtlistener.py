"""CourtListener REST API ingester.

Ingests legal signals related to trafficking, missing persons, and exploitation
from CourtListener search results.
"""

import os
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingesters.base import BaseIngester
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal
from app.services.legal_ai_enrichment import LegalAIEnricher

_COURTLISTENER_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
_DEFAULT_QUERIES = [
    '"human trafficking"',
    '"sex trafficking"',
    '"labor trafficking"',
    '"forced labor"',
    '"missing person"',
    '"parental kidnapping"',
    '"human smuggling"',
]


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _detect_signal_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["trafficking", "forced labor", "modern slavery", "exploitation"]):
        return "trafficking_indicator"
    if any(k in t for k in ["missing", "kidnapp", "abduction", "parental"]):
        return "missing_person"
    if any(k in t for k in ["smuggling", "border", "transport"]):
        return "smuggling_indicator"
    if any(k in t for k in ["assault", "homicide", "murder", "violence", "rape"]):
        return "violent_crime"
    return "legal_reference"


def _risk_from_signal_type(signal_type: str) -> float:
    return {
        "trafficking_indicator": 78.0,
        "missing_person": 72.0,
        "smuggling_indicator": 70.0,
        "violent_crime": 74.0,
        "legal_reference": 62.0,
    }.get(signal_type, 60.0)


class CourtListenerIngester(BaseIngester):
    """Ingest legal references from CourtListener REST API search endpoint."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        api_token: str | None = None,
        queries: list[str] | None = None,
        pages_per_query: int = 2,
        page_size: int = 20,
        ai_enrich: bool = True,
        ai_max_records: int = 25,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ):
        super().__init__(session)
        self.api_token = api_token or os.getenv("COURTLISTENER_API_TOKEN")
        self.queries = [q.strip() for q in (queries or _DEFAULT_QUERIES) if q and q.strip()]
        self.pages_per_query = max(1, min(pages_per_query, 10))
        self.page_size = max(1, min(page_size, 100))
        self.ai_enrich_enabled = ai_enrich
        self.ai_max_records = max(0, min(ai_max_records, 200))
        self.ai_enriched_count = 0
        self.ai_enricher = (
            LegalAIEnricher(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            if ai_enrich
            else None
        )

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        if not self.api_token:
            return {
                **self.report(),
                "skipped": True,
                "reason": "CourtListener API token not configured",
                "source": "courtlistener",
            }

        total_results_seen = 0
        total_records_created = 0

        headers = {"Authorization": f"Token {self.api_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(headers=headers, timeout=25, follow_redirects=True) as client:
            for query in self.queries:
                try:
                    created, seen = await self._ingest_query(client, query)
                    total_results_seen += seen
                    total_records_created += created
                except Exception:
                    self.error_count += 1

        await self.session.commit()

        return {
            **self.report(),
            "queries_used": self.queries,
            "results_seen": total_results_seen,
            "cases_created": total_records_created,
            "ai_enabled": bool(self.ai_enricher and self.ai_enricher.enabled),
            "ai_provider": self.ai_enricher.provider if self.ai_enricher and self.ai_enricher.enabled else None,
            "ai_enriched_count": self.ai_enriched_count,
            "source": "courtlistener",
        }

    async def _ingest_query(self, client: httpx.AsyncClient, query: str) -> tuple[int, int]:
        url = _COURTLISTENER_SEARCH_URL
        params: dict[str, Any] | None = {"q": query, "page_size": self.page_size}

        page_no = 0
        seen = 0
        created = 0

        while page_no < self.pages_per_query and url:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results") or []
            if not results:
                break

            for result in results:
                seen += 1
                try:
                    if await self._process_result(result, query):
                        created += 1
                        self.imported_count += 1
                except Exception:
                    self.error_count += 1

            page_no += 1
            next_url = data.get("next")
            url = next_url if next_url else ""
            params = None

        return created, seen

    async def _process_result(self, result: dict[str, Any], query: str) -> bool:
        cluster_id = result.get("cluster_id")
        if not cluster_id:
            return False

        court_id = str(result.get("court_id") or "unknown")
        case_name = (result.get("caseName") or result.get("caseNameFull") or "CourtListener Case").strip()
        absolute_url = result.get("absolute_url") or ""
        source_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else None

        entity_id = f"CL-CASE-{cluster_id}"[:64]
        signal_id = f"CL-SIG-{cluster_id}"[:64]
        case_id = f"CL-REF-{cluster_id}"[:64]

        existing = await self.session.execute(select(Entity).where(Entity.entity_id == entity_id))
        if existing.scalar_one_or_none():
            return False

        date_filed = result.get("dateFiled") or ""
        court_name = result.get("court") or "Unknown Court"
        docket_number = result.get("docketNumber") or ""
        citation = result.get("citation") or []
        citations_str = "; ".join(citation[:4]) if isinstance(citation, list) else str(citation)
        judge = result.get("judge") or ""
        posture = result.get("posture") or ""
        status = result.get("status") or ""
        snippets = result.get("opinions") or []
        snippet = ""
        if snippets and isinstance(snippets, list):
            first = snippets[0] or {}
            snippet = str(first.get("snippet") or "").strip()

        full_text = " ".join(
            p for p in [query, case_name, court_name, citations_str, snippet, posture, status] if p
        )
        signal_type = _detect_signal_type(full_text)
        confidence = min(0.93, max(0.65, 0.70 + (_coerce_float(result.get("citeCount"), 0) / 100.0)))
        risk_score = _risk_from_signal_type(signal_type)

        ai_data: dict[str, Any] | None = None
        if (
            self.ai_enricher
            and self.ai_enricher.enabled
            and self.ai_enrich_enabled
            and self.ai_enriched_count < self.ai_max_records
            and (snippet or case_name)
        ):
            try:
                ai_data = await self.ai_enricher.enrich(
                    case_name=case_name,
                    court_name=court_name,
                    query=query,
                    snippet=snippet,
                    docket_number=docket_number,
                    date_filed=date_filed,
                )
                if ai_data:
                    self.ai_enriched_count += 1
                    ai_conf = _coerce_float(ai_data.get("confidence"), confidence)
                    confidence = min(0.97, max(0.55, ai_conf))
                    risk_score = min(
                        99.0,
                        max(0.0, risk_score + _coerce_float(ai_data.get("risk_adjustment"), 0.0)),
                    )
            except Exception:
                # AI enrichment is best-effort and must not block ingestion.
                ai_data = None

        entity = Entity(
            entity_id=entity_id,
            canonical_name=case_name[:512],
            entity_type="organization",
            confidence=confidence,
            source_count=1,
            extra_metadata={
                "data_class": "sensitive_public",
                "source": "CourtListener",
                "usage": "reference_only",
                "court_id": court_id,
                "court_name": court_name,
                "cluster_id": cluster_id,
                "docket_id": result.get("docket_id"),
                "docket_number": docket_number,
                "date_filed": date_filed,
                "citation": citation,
                "judge": judge,
                "status": status,
                "query": query,
                "record_badge": "Court Record (Reference Data)",
            },
        )
        self.session.add(entity)

        evidence_parts = [
            f"Case: {case_name}",
            f"Court: {court_name}",
            f"Filed: {date_filed}" if date_filed else "",
            f"Docket: {docket_number}" if docket_number else "",
            f"Citations: {citations_str}" if citations_str else "",
            f"Snippet: {snippet[:700]}" if snippet else "",
            f"AI Summary: {str(ai_data.get('summary') or '').strip()}" if ai_data else "",
            f"Query: {query}",
        ]
        evidence = " | ".join(p for p in evidence_parts if p)[:2000]

        signal = Signal(
            signal_id=signal_id,
            entity_id=entity_id,
            signal_type=signal_type,
            label="CourtListener Legal Signal",
            confidence=confidence,
            evidence=evidence,
            source_url=source_url,
            source_name="CourtListener",
            extra_metadata={
                "data_class": "sensitive_public",
                "source": "CourtListener",
                "usage": "reference_only",
                "court_id": court_id,
                "cluster_id": cluster_id,
                "query": query,
                "ai": ai_data or {},
            },
        )
        self.session.add(signal)

        notes = (
            f"CourtListener legal reference for '{case_name}' in {court_name}. "
            f"Potential correlation against trafficking/missing-person indicators from legal text. "
            "This is reference data only and not a legal determination."
        )

        case = Case(
            case_id=case_id,
            status="open",
            risk_score=risk_score,
            confidence_score=confidence,
            system_confidence=confidence,
            entity_ids=[entity_id],
            signal_ids=[signal_id],
            notes=notes,
            extra_metadata={
                "data_class": "sensitive_public",
                "source": "CourtListener",
                "usage": "reference_only",
                "ai": ai_data or {},
                "interpretation": (
                    "Potential correlation detected between legal records and external signals; "
                    "this is not a legal determination."
                ),
            },
        )
        self.session.add(case)

        return True
