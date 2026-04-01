"""GDELT 2.0 DOC API ingester for trafficking-related OSINT articles."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingesters.base import BaseIngester
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_DEFAULT_QUERIES = [
    '"human trafficking"',
    '"labor trafficking"',
    '"sex trafficking"',
    '"forced labor"',
]


class GDELTIngester(BaseIngester):
    """Ingest article leads from GDELT DOC API (v2 endpoint)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        queries: list[str] | None = None,
        max_records_per_query: int = 25,
        timespan: str = "7d",
    ) -> None:
        super().__init__(session)
        cleaned_queries = [q.strip() for q in (queries or _DEFAULT_QUERIES) if q and q.strip()]
        self.queries = cleaned_queries or _DEFAULT_QUERIES
        self.max_records_per_query = max(1, min(max_records_per_query, 250))
        self.timespan = timespan.strip() or "7d"

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        records_loaded = 0
        created_cases = 0

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for query in self.queries:
                try:
                    articles = await self._fetch_articles(client, query)
                except Exception:
                    self.error_count += 1
                    continue

                records_loaded += len(articles)
                for article in articles:
                    try:
                        created = await self._process_article(article)
                        if created:
                            created_cases += 1
                            self.imported_count += 1
                    except Exception:
                        self.error_count += 1

        await self.session.commit()

        return {
            **self.report(),
            "source": "gdelt",
            "queries_used": self.queries,
            "records_loaded": records_loaded,
            "cases_created": created_cases,
            "timespan": self.timespan,
            "api_endpoint": _GDELT_DOC_API,
        }

    async def _fetch_articles(self, client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(self.max_records_per_query),
            "format": "json",
            "sort": "HybridRel",
            "timespan": self.timespan,
        }
        response = await client.get(_GDELT_DOC_API, params=params)
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("articles") or []
        if not isinstance(articles, list):
            return []
        return [item for item in articles if isinstance(item, dict)]

    async def _process_article(self, article: dict[str, Any]) -> bool:
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or "").strip()
        if not url or not title:
            return False

        key = hashlib.sha1(url.encode("utf-8")).hexdigest().upper()[:20]
        case_id = f"GDELT-CASE-{key}"[:64]
        entity_id = f"GDELT-ENTITY-{key}"[:64]
        signal_id = f"GDELT-SIG-{key}"[:64]

        existing_case = await self.session.execute(select(Case).where(Case.case_id == case_id))
        if existing_case.scalar_one_or_none():
            return False

        seen_date = str(article.get("seendate") or "").strip()
        detected_at = self._parse_dt(seen_date)

        source_domain = str(article.get("domain") or "").strip()
        source_country = str(article.get("sourcecountry") or "").strip()
        language = str(article.get("language") or "").strip()
        tone = article.get("tone")
        image = str(article.get("socialimage") or "").strip()
        snippet = str(article.get("snippet") or "").strip()

        indicators = self._detect_indicators(f"{title} {snippet}")
        signal_type = indicators[0] if indicators else "ngo_report"
        confidence = min(0.82, 0.62 + (len(indicators) * 0.04))
        risk_score = min(76.0, 44.0 + (len(indicators) * 4.0))

        entity = Entity(
            entity_id=entity_id,
            canonical_name=title[:500],
            entity_type="organization",
            confidence=0.70,
            source_count=1,
            extra_metadata={
                "source": "GDELT",
                "source_label": "gdelt",
                "data_class": "public_osint",
                "usage": "investigative_lead",
                "url": url,
                "domain": source_domain,
                "source_country": source_country,
            },
        )
        self.session.add(entity)

        signal = Signal(
            signal_id=signal_id,
            entity_id=entity_id,
            signal_type=signal_type,
            label="GDELT Media Lead",
            confidence=round(confidence, 2),
            evidence=(f"{title}. {snippet}")[:2000],
            raw_text_snippet=snippet[:500],
            source_name="gdelt",
            source_url=url,
            detected_at=detected_at,
            extra_metadata={
                "source": "GDELT",
                "source_label": "gdelt",
                "data_class": "public_osint",
                "usage": "investigative_lead",
                "domain": source_domain,
                "source_country": source_country,
                "language": language,
                "tone": tone,
                "socialimage": image,
                "indicators": indicators,
            },
        )
        self.session.add(signal)

        case = Case(
            case_id=case_id,
            status="under_review",
            risk_score=round(risk_score, 2),
            confidence_score=round(confidence, 2),
            system_confidence=round(confidence, 2),
            entity_ids=[entity_id],
            signal_ids=[signal_id],
            notes=(
                f"GDELT article lead from {source_domain or 'unknown source'} "
                f"({source_country or 'unknown country'}) with indicators: "
                f"{', '.join(indicators[:6]) if indicators else 'none'}"
            ),
            extra_metadata={
                "source": "GDELT",
                "source_label": "gdelt",
                "data_class": "public_osint",
                "usage": "investigative_lead",
                "url": url,
                "domain": source_domain,
                "source_country": source_country,
                "indicator_count": len(indicators),
                "timespan": self.timespan,
            },
        )
        self.session.add(case)
        return True

    def _parse_dt(self, value: str) -> datetime:
        value = value.strip()
        if not value:
            return datetime.now(UTC)
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
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

    def _detect_indicators(self, content: str) -> list[str]:
        content = content.lower()
        indicators: list[str] = []
        if any(token in content for token in ("labor trafficking", "forced labor", "exploitation", "wage theft")):
            indicators.append("labor_trafficking_indicator")
        if any(token in content for token in ("sex trafficking", "sexual exploitation", "commercial sex", "minor")):
            indicators.append("sex_trafficking_indicator")
        if any(token in content for token in ("coercion", "threat", "debt bondage", "forced")):
            indicators.append("coercion_language_detected")
        if any(token in content for token in ("smuggling", "border", "migration", "cross-border")):
            indicators.append("border_crossing_anomaly")
        if any(token in content for token in ("police", "law enforcement", "arrest", "investigation", "prosecution")):
            indicators.append("law_enforcement_report")
        if not indicators:
            indicators.append("ngo_report")
        return indicators
