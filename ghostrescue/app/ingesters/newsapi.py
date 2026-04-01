"""NewsAPI ingester for trafficking-related news articles."""
import uuid
from datetime import datetime, UTC
from typing import Any

import aiohttp
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.models.entity import Entity
from app.models.signal import Signal
from app.ingesters.base import BaseIngester


class NewsAPIIngester(BaseIngester):
    """Ingest trafficking-related articles from NewsAPI."""

    def __init__(self, session: AsyncSession, api_key: str | None = None):
        super().__init__(session)
        settings = get_settings()
        self.api_key = api_key or settings.newsapi_key
        self.base_url = "https://newsapi.org/v2/everything"
        
        # Search queries for trafficking indicators
        self.search_queries = [
            "human trafficking",
            "labor trafficking",
            "sex trafficking",
            "forced labor",
            "human smuggling",
            "modern slavery",
            "migrant exploitation",
            "document fraud border",
            "labor exploitation",
        ]

    async def ingest(self) -> dict[str, Any]:
        """Ingest articles from NewsAPI."""
        self.start_time = datetime.now()
        
        if not self.api_key:
            print("⚠️  NewsAPI key not configured - skipping news ingestion")
            return {
                **self.report(),
                "skipped": True,
                "reason": "API key not configured",
            }

        articles_found = 0
        signals_created = 0

        async with aiohttp.ClientSession() as http_session:
            for query in self.search_queries:
                print(f"  📰 Searching NewsAPI for: {query}")
                try:
                    articles = await self._search_articles(http_session, query)
                    articles_found += len(articles)
                    
                    for article in articles:
                        try:
                            created = await self._process_article(article)
                            signals_created += created
                            self.imported_count += created
                        except Exception:
                            self.error_count += 1
                            
                except Exception as e:
                    print(f"    Error searching for '{query}': {str(e)[:100]}")
                    self.error_count += 1

        await self.session.commit()

        return {
            **self.report(),
            "articles_found": articles_found,
            "signals_created": signals_created,
            "source": "newsapi",
        }

    async def _search_articles(self, session: aiohttp.ClientSession, query: str) -> list[dict]:
        """Search for articles via NewsAPI."""
        params = {
            "q": query,
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": 20,
            "apiKey": self.api_key,
        }

        try:
            async with session.get(self.base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("articles", [])
                else:
                    print(f"    NewsAPI error: {resp.status}")
                    return []
        except Exception as e:
            print(f"    Request failed: {str(e)[:50]}")
            return []

    async def _process_article(self, article: dict) -> int:
        """Process a news article and create entities/signals."""
        title = article.get("title", "")
        description = article.get("description", "")
        source = article.get("source", {}).get("name", "news")
        published_at = article.get("publishedAt", datetime.now(UTC).isoformat())
        url = article.get("url", "")
        source_name = f"newsapi-{source}"

        if url:
            existing_signal = await self.session.execute(
                select(Signal.signal_id)
                .where(Signal.source_url == url)
                .where(Signal.source_name == source_name)
                .limit(1)
            )
            if existing_signal.scalar_one_or_none():
                # Article already ingested for this source; avoid duplicate signals.
                return 0

        # Create source entity if doesn't exist
        source_entity_id = f"NEWS-SOURCE-{source.upper()[:20].replace(' ', '_')}"
        
        try:
            existing = await self.session.execute(
                select(Entity).where(Entity.entity_id == source_entity_id)
            )
            if not existing.scalar_one_or_none():
                source_entity = Entity(
                    entity_id=source_entity_id,
                    canonical_name=f"News: {source}",
                    entity_type="organization",
                    confidence=0.8,
                    extra_metadata={"source_type": "news_outlet", "articles_indexed": 1}
                )
                self.session.add(source_entity)
        except Exception:
            pass

        # Create signal from article
        signal_types = self._detect_signal_types(title, description)
        for signal_type in signal_types:
            signal = Signal(
                signal_id=f"SIG-{uuid.uuid4().hex[:12].upper()}",
                signal_type=signal_type,
                label=signal_type.replace("_", " ").title(),
                confidence=0.7,
                evidence=f"Article: {title[:100]}",
                source_name=source_name,
                source_url=url,
                detected_at=datetime.fromisoformat(published_at.replace('Z', '+00:00')) if 'Z' in published_at else datetime.now(UTC),
                extra_metadata={
                    "article_title": title,
                    "article_url": url,
                    "source_type": "news",
                }
            )
            self.session.add(signal)

        return len(signal_types)

    def _detect_signal_types(self, title: str, description: str) -> list[str]:
        """Detect trafficking signal types from article content."""
        content = (title + " " + description).lower()
        signals = []

        if any(word in content for word in ["labor", "forced labor", "exploitation", "wages", "working"]):
            signals.append("labor_trafficking_indicator")
        
        if any(word in content for word in ["sex", "exploitation", "prostitution", "commercial"]):
            signals.append("sex_trafficking_indicator")
        
        if any(word in content for word in ["document", "visa", "fake", "fraud", "forged"]):
            signals.append("document_fraud_detected")
        
        if any(word in content for word in ["coercion", "force", "threat", "debt", "bondage"]):
            signals.append("coercion_language_detected")
        
        if any(word in content for word in ["border", "crossing", "smuggling", "migrate", "migrant"]):
            signals.append("border_crossing_anomaly")
        
        if any(word in content for word in ["report", "investigation", "arrest", "police", "law enforcement"]):
            signals.append("law_enforcement_report")

        return signals if signals else ["ngo_report"]
