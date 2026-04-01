import base64
import logging
from typing import Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 10) -> list[dict]:
        ...


class NullSearchProvider:
    async def search(self, query: str, limit: int = 10) -> list[dict]:
        return []


class CompositeSearchProvider:
    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
        for provider in self.providers:
            try:
                provider_results = await provider.search(query, limit=limit)
            except Exception:
                logger.exception("discovery.provider_failed", extra={"provider": provider.__class__.__name__})
                continue
            for result in provider_results:
                url = result.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(result)
                if len(results) >= limit:
                    return results
        return results


class DuckDuckGoHtmlSearchProvider:
    """Simple discovery provider using DuckDuckGo's public HTML endpoint."""

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        params = {"q": query}
        headers = {"User-Agent": "Mozilla/5.0 GhostScraper/1.0"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get("https://duckduckgo.com/html/", params=params)

        soup = BeautifulSoup(response.text, "lxml")
        if soup.find("form", attrs={"id": "challenge-form"}):
            return []
        results: list[dict] = []
        seen: set[str] = set()

        for link in soup.select("a.result__a"):
            href = (link.get("href") or "").strip()
            if not href:
                continue
            resolved = self._resolve_ddg_redirect(href)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            results.append({"url": resolved, "title": link.get_text(" ", strip=True), "source": "duckduckgo_html"})
            if len(results) >= limit:
                break

        return results

    def _resolve_ddg_redirect(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            encoded = parse_qs(parsed.query).get("uddg", [""])[0]
            if encoded:
                return unquote(encoded)
        return url


class BingHtmlSearchProvider:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        params = {"q": query}
        headers = {"User-Agent": "Mozilla/5.0 GhostScraper/1.0"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get("https://www.bing.com/search", params=params)

        soup = BeautifulSoup(response.text, "lxml")
        results: list[dict] = []
        seen: set[str] = set()

        for item in soup.select("li.b_algo h2 a"):
            href = (item.get("href") or "").strip()
            if not href:
                continue
            resolved = self._normalize_href(href)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            results.append({"url": resolved, "title": item.get_text(" ", strip=True), "source": "bing_html"})
            if len(results) >= limit:
                break

        return results

    def _normalize_href(self, href: str) -> str | None:
        url = urljoin("https://www.bing.com", href)
        parsed = urlparse(url)
        if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
            encoded = parse_qs(parsed.query).get("u", [""])[0]
            if encoded.startswith("a1"):
                decoded = self._decode_bing_target(encoded[2:])
                if decoded:
                    return decoded
        if not parsed.scheme.startswith("http"):
            return None
        return url

    def _decode_bing_target(self, value: str) -> str | None:
        padded = value + "=" * (-len(value) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            if decoded.startswith("http"):
                return decoded
        except Exception:
            return None
        return None


class GoogleHtmlSearchProvider:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        params = {"q": query, "hl": "en"}
        headers = {"User-Agent": "Mozilla/5.0 GhostScraper/1.0"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get("https://www.google.com/search", params=params)

        soup = BeautifulSoup(response.text, "lxml")
        if soup.select_one("form#captcha-form") or "unusual traffic" in response.text.lower():
            return []

        results: list[dict] = []
        seen: set[str] = set()
        for item in soup.select("a[href] h3"):
            parent = item.parent
            if parent is None:
                continue
            href = (parent.get("href") or "").strip()
            resolved = self._normalize_href(href)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            results.append({"url": resolved, "title": item.get_text(" ", strip=True), "source": "google_html"})
            if len(results) >= limit:
                break
        return results

    def _normalize_href(self, href: str) -> str | None:
        if href.startswith("/url?"):
            parsed = urlparse(href)
            target = parse_qs(parsed.query).get("q", [""])[0]
            if target.startswith("http"):
                return target
            return None
        parsed = urlparse(href)
        if parsed.scheme.startswith("http"):
            return href
        return None


class YahooHtmlSearchProvider:
    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        params = {"p": query}
        headers = {"User-Agent": "Mozilla/5.0 GhostScraper/1.0"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get("https://search.yahoo.com/search", params=params)

        soup = BeautifulSoup(response.text, "lxml")
        results: list[dict] = []
        seen: set[str] = set()
        for item in soup.select("div#web h3 a, div.algo h3 a"):
            href = (item.get("href") or "").strip()
            resolved = self._normalize_href(href)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            results.append({"url": resolved, "title": item.get_text(" ", strip=True), "source": "yahoo_html"})
            if len(results) >= limit:
                break
        return results

    def _normalize_href(self, href: str) -> str | None:
        url = urljoin("https://search.yahoo.com", href)
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            return None
        return url


def build_search_provider(settings: Settings) -> SearchProvider:
    provider = settings.discovery_provider.lower().strip()
    if provider == "duckduckgo_html":
        return DuckDuckGoHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds)
    if provider == "bing_html":
        return BingHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds)
    if provider == "google_html":
        return GoogleHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds)
    if provider == "yahoo_html":
        return YahooHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds)
    if provider in {"auto", "composite", "fallback"}:
        return CompositeSearchProvider(
            [
                DuckDuckGoHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds),
                BingHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds),
                GoogleHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds),
                YahooHtmlSearchProvider(timeout_seconds=settings.discovery_timeout_seconds),
            ]
        )
    return NullSearchProvider()
