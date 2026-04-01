"""Polaris Project HTML ingester (API-less, public web extraction)."""

from __future__ import annotations

import json
import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingesters.base import BaseIngester
from app.models.case import Case
from app.models.entity import Entity
from app.models.signal import Signal

_DEFAULT_BASE_URL = "https://polarisproject.org"
_DEFAULT_SITEMAP = "https://polarisproject.org/sitemap.xml"

_ALLOWED_PATH_HINTS = (
    "human-trafficking",
    "blog",
    "news",
    "resources",
    "our-work",
    "publications",
    "research",
)


class PolarisIngester(BaseIngester):
    """Ingest public Polaris Project pages as OSINT intelligence leads."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        sitemap_url: str = _DEFAULT_SITEMAP,
        seed_urls: list[str] | None = None,
        max_pages: int = 40,
        data_file: str | None = None,
    ) -> None:
        super().__init__(session)
        self.sitemap_url = sitemap_url
        self.seed_urls = seed_urls or [
            f"{_DEFAULT_BASE_URL}/human-trafficking/",
            f"{_DEFAULT_BASE_URL}/our-work/",
            f"{_DEFAULT_BASE_URL}/blog/",
            f"{_DEFAULT_BASE_URL}/resources/",
        ]
        self.max_pages = max(1, min(max_pages, 200))
        self.data_file = Path(data_file) if data_file else None

    async def ingest(self) -> dict[str, Any]:
        self.start_time = datetime.now()

        if self.data_file:
            pages = self._load_file_pages()
            if not pages:
                return {
                    **self.report(),
                    "skipped": True,
                    "reason": "No valid Polaris records in data_file",
                    "source": "polaris_project",
                    "mode": "file",
                }

            created_cases = 0
            for page in pages[: self.max_pages]:
                try:
                    created = await self._process_page(page)
                    if created:
                        created_cases += 1
                        self.imported_count += 1
                except Exception:
                    self.error_count += 1

            await self.session.commit()

            return {
                **self.report(),
                "source": "polaris_project",
                "pages_discovered": len(pages),
                "pages_processed": min(len(pages), self.max_pages),
                "cases_created": created_cases,
                "mode": "file",
            }

        pages = await self._discover_pages()
        if not pages:
            return {
                **self.report(),
                "skipped": True,
                "reason": "No candidate Polaris pages discovered",
                "source": "polaris_project",
            }

        selected = pages[: self.max_pages]
        created_cases = 0
        fetched_pages = 0

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for url in selected:
                try:
                    page = await self._fetch_page(client, url)
                    if not page:
                        continue
                    fetched_pages += 1
                    created = await self._process_page(page)
                    if created:
                        created_cases += 1
                        self.imported_count += 1
                except Exception:
                    self.error_count += 1

        await self.session.commit()

        if selected and fetched_pages == 0:
            return {
                **self.report(),
                "source": "polaris_project",
                "pages_discovered": len(pages),
                "pages_processed": len(selected),
                "cases_created": 0,
                "mode": "live_html",
                "skipped": True,
                "reason": "Live Polaris pages were not accessible from this runtime (likely 403 anti-bot blocking)",
            }

        return {
            **self.report(),
            "source": "polaris_project",
            "pages_discovered": len(pages),
            "pages_processed": len(selected),
            "cases_created": created_cases,
            "mode": "live_html",
        }

    def _load_file_pages(self) -> list[dict[str, Any]]:
        if not self.data_file:
            return []
        if not self.data_file.exists():
            raise FileNotFoundError(f"file not found: {self.data_file}")

        raw = json.loads(self.data_file.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Polaris data_file must be a JSON list of records")

        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or item.get("content") or "").strip()
            if not url or not body:
                continue
            dt_raw = str(item.get("published_at") or "").strip()
            published_at = datetime.now(UTC)
            if dt_raw:
                try:
                    if dt_raw.endswith("Z"):
                        dt_raw = dt_raw.replace("Z", "+00:00")
                    parsed = datetime.fromisoformat(dt_raw)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    published_at = parsed.astimezone(UTC)
                except Exception:
                    pass
            out.append({"url": url, "title": title or "Polaris Project Content", "body": body, "published_at": published_at})
        return out

    async def _discover_pages(self) -> list[str]:
        urls: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                urls = await self._collect_sitemap_urls(client, self.sitemap_url)
        except Exception:
            urls = []

        candidates = urls + self.seed_urls
        normalized: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            clean = self._normalize_url(url)
            if not clean or clean in seen:
                continue
            if not self._is_allowed_url(clean):
                continue
            seen.add(clean)
            normalized.append(clean)
        return normalized

    async def _collect_sitemap_urls(self, client: httpx.AsyncClient, sitemap_url: str, depth: int = 0) -> list[str]:
        if depth > 3:
            return []
        response = await client.get(sitemap_url)
        response.raise_for_status()
        parsed = self._parse_sitemap(response.text)
        if not parsed:
            return []

        sitemap_children = [u for u in parsed if u.lower().endswith(".xml") and "sitemap" in u.lower()]
        page_urls = [u for u in parsed if u not in sitemap_children]

        for child in sitemap_children[:20]:
            try:
                page_urls.extend(await self._collect_sitemap_urls(client, child, depth + 1))
            except Exception:
                continue
        return page_urls

    def _parse_sitemap(self, raw_xml: str) -> list[str]:
        out: list[str] = []
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError:
            return out

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for node in root.findall(".//sm:url/sm:loc", ns):
            if node.text:
                out.append(node.text.strip())
        if out:
            return out

        for node in root.findall(".//loc"):
            if node.text:
                out.append(node.text.strip())
        return out

    def _normalize_url(self, url: str) -> str | None:
        if not url:
            return None
        url = url.strip()
        if not url.startswith("http"):
            url = urljoin(_DEFAULT_BASE_URL, url)
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") + "/"

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if "polarisproject.org" not in parsed.netloc.lower():
            return False
        path = parsed.path.lower().strip("/")
        if not path:
            return False
        if any(path.startswith(prefix) for prefix in ("wp-content", "wp-includes", "tag", "author", "category")):
            return False
        if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".css", ".js", ".xml", ".pdf", ".woff", ".woff2")):
            return False
        if any(segment in path for segment in ("/feed", "/amp")):
            return False
        # Keep mission-relevant path hints preferred, but allow clean content pages too.
        return any(hint in path for hint in _ALLOWED_PATH_HINTS) or path.count("/") >= 1

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        response = await client.get(url)
        if response.status_code != 200:
            return None
        html = response.text
        title = self._extract_title(html)
        body_text = self._extract_body_text(html)
        if len(body_text) < 180:
            return None
        published_at = self._extract_published_at(html)

        return {
            "url": url,
            "title": title,
            "body": body_text,
            "published_at": published_at,
        }

    async def _process_page(self, page: dict[str, Any]) -> bool:
        url = str(page["url"])
        title = str(page["title"])
        body = str(page["body"])
        published_at = page.get("published_at") or datetime.now(UTC)

        key = hashlib.sha1(url.encode("utf-8")).hexdigest().upper()[:20]
        case_id = f"POLARIS-CASE-{key}"[:64]
        entity_id = f"POLARIS-ENTITY-{key}"[:64]
        signal_id = f"POLARIS-SIG-{key}"[:64]

        existing_case = await self.session.execute(select(Case).where(Case.case_id == case_id))
        if existing_case.scalar_one_or_none():
            return False

        indicators = self._detect_indicators(f"{title}\n{body}")
        signal_type = indicators[0] if indicators else "ngo_report"
        confidence = 0.64 + min(0.2, len(indicators) * 0.04)
        risk_score = min(72.0, 42.0 + len(indicators) * 3.5)

        existing_entity = await self.session.execute(select(Entity).where(Entity.entity_id == entity_id))
        entity = existing_entity.scalar_one_or_none()
        if not entity:
            entity = Entity(
                entity_id=entity_id,
                canonical_name=title[:500] or "Polaris Project Content",
                entity_type="organization",
                confidence=0.72,
                source_count=1,
                extra_metadata={
                    "source": "Polaris Project",
                    "source_label": "polaris_project",
                    "data_class": "public_osint",
                    "usage": "investigative_lead",
                    "url": url,
                },
            )
            self.session.add(entity)

        signal = Signal(
            signal_id=signal_id,
            entity_id=entity_id,
            signal_type=signal_type,
            label="Polaris Project Lead",
            confidence=round(min(0.9, confidence), 2),
            evidence=(f"{title}. {body[:1800]}")[:2000],
            raw_text_snippet=body[:500],
            source_name="polaris_project",
            source_url=url,
            detected_at=published_at,
            extra_metadata={
                "source": "Polaris Project",
                "source_label": "polaris_project",
                "data_class": "public_osint",
                "usage": "investigative_lead",
                "indicators": indicators,
                "published_at": published_at.isoformat(),
            },
        )
        self.session.add(signal)

        case = Case(
            case_id=case_id,
            status="under_review",
            risk_score=round(risk_score, 2),
            confidence_score=round(min(0.88, confidence), 2),
            system_confidence=round(min(0.88, confidence), 2),
            entity_ids=[entity_id],
            signal_ids=[signal_id],
            notes=(
                f"Polaris Project public-content lead extracted from {url}. "
                f"Detected indicators: {', '.join(indicators[:6]) if indicators else 'none'}"
            ),
            extra_metadata={
                "source": "Polaris Project",
                "source_label": "polaris_project",
                "data_class": "public_osint",
                "usage": "investigative_lead",
                "url": url,
                "indicator_count": len(indicators),
            },
        )
        self.session.add(case)
        return True

    def _extract_title(self, html: str) -> str:
        patterns = [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r"<title>(.*?)</title>",
            r"<h1[^>]*>(.*?)</h1>",
        ]
        for pattern in patterns:
            m = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                return self._clean_text(m.group(1))[:500]
        return "Polaris Project Content"

    def _extract_published_at(self, html: str) -> datetime:
        patterns = [
            r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
            r'<time[^>]+datetime=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip()
            try:
                if raw.endswith("Z"):
                    raw = raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except Exception:
                continue
        return datetime.now(UTC)

    def _extract_body_text(self, html: str) -> str:
        article_match = re.search(r"<article[^>]*>(.*?)</article>", html, flags=re.IGNORECASE | re.DOTALL)
        block = article_match.group(1) if article_match else html

        # Remove scripts/styles and collapse to plain text.
        block = re.sub(r"<script[\\s\\S]*?</script>", " ", block, flags=re.IGNORECASE)
        block = re.sub(r"<style[\\s\\S]*?</style>", " ", block, flags=re.IGNORECASE)
        block = re.sub(r"<noscript[\\s\\S]*?</noscript>", " ", block, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", block)
        return self._clean_text(text)

    def _clean_text(self, value: str) -> str:
        value = unescape(value)
        value = re.sub(r"\\s+", " ", value)
        return value.strip()

    def _detect_indicators(self, content: str) -> list[str]:
        content = content.lower()
        indicators: list[str] = []
        if any(token in content for token in ("labor trafficking", "forced labor", "wage theft", "exploitation")):
            indicators.append("labor_trafficking_indicator")
        if any(token in content for token in ("sex trafficking", "commercial sex", "minor", "sexual exploitation")):
            indicators.append("sex_trafficking_indicator")
        if any(token in content for token in ("coercion", "threat", "debt bondage", "forced")):
            indicators.append("coercion_language_detected")
        if any(token in content for token in ("smuggling", "border", "migration", "cross-border")):
            indicators.append("border_crossing_anomaly")
        if any(token in content for token in ("investigation", "prosecution", "law enforcement", "arrest")):
            indicators.append("law_enforcement_report")
        if not indicators:
            indicators.append("ngo_report")
        return indicators
