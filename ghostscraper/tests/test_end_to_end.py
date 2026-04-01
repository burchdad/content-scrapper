from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes_jobs import get_orchestrator
from app.main import app
from app.models.fetch import FetchedPage
from app.services.scrape_orchestrator import ScrapeOrchestrator


class FakeStaticFetcher:
    async def fetch(self, url: str) -> FetchedPage:
        media_hosts = ["media", "giphy.com", "tenor.com", "reddit.com"]
        fixture = "tests/fixtures/media_page.html" if any(host in url for host in media_hosts) else "tests/fixtures/listing_page.html"
        html = Path(fixture).read_text(encoding="utf-8")
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            html=html,
            content_type="text/html",
            mode="static",
            response_headers={},
        )


class FakeDynamicFetcher:
    async def fetch(self, url, options):  # pragma: no cover - not used here
        raise RuntimeError("not expected")


class FakeDynamicFetcherMissingBrowser:
    async def fetch(self, url, options):
        raise RuntimeError("BrowserType.launch: Executable doesn't exist at /tmp/playwright")


class FakeSearchProvider:
    async def search(self, query: str, limit: int = 10):
        if "video" in query.lower() or "media" in query.lower():
            return [{"url": "https://giphy.com/trending-gifs"}]
        return [{"url": "https://listing.example.com/home/123"}]


class FakeSearchProviderDogQuery:
    async def search(self, query: str, limit: int = 10):
        if "dog" in query.lower() or "video" in query.lower() or "media" in query.lower():
            return [
                {"url": "https://giphy.com/trending-gifs", "title": "Trending GIFs"},
                {
                    "url": "https://media.example.com/top-dog-video-compilation",
                    "title": "Top dog video compilation",
                },
            ]
        return [{"url": "https://listing.example.com/home/123"}]


def test_jobs_scrape_endpoint_end_to_end(monkeypatch):
    orchestrator = ScrapeOrchestrator(
        static_fetcher=FakeStaticFetcher(),
        dynamic_fetcher=FakeDynamicFetcher(),
        search_provider=FakeSearchProvider(),
    )

    async def fake_robots(url: str, user_agent: str = "*"):
        return True

    monkeypatch.setattr("app.services.scrape_orchestrator.robots_allows", fake_robots)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator

    client = TestClient(app)
    payload = {
        "query": "find real estate listing details and photos",
        "max_pages": 1,
        "mode": "static",
    }

    response = client.post("/api/v1/jobs/scrape", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["records"]) >= 1
    assert body["records"][0]["record_type"] == "real_estate"
    assert body["stats"]["pages_processed"] == 1

    app.dependency_overrides.clear()


def test_jobs_scrape_endpoint_media_assets(monkeypatch):
    orchestrator = ScrapeOrchestrator(
        static_fetcher=FakeStaticFetcher(),
        dynamic_fetcher=FakeDynamicFetcher(),
        search_provider=FakeSearchProvider(),
    )

    async def fake_robots(url: str, user_agent: str = "*"):
        return True

    monkeypatch.setattr("app.services.scrape_orchestrator.robots_allows", fake_robots)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator

    client = TestClient(app)
    payload = {
        "query": "pull all images, videos, and social media assets for this creator campaign",
        "max_pages": 1,
        "mode": "static",
    }

    response = client.post("/api/v1/jobs/scrape", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["records"][0]["record_type"] == "media"
    assert any(video.endswith("/video/trailer.mp4") for video in body["records"][0]["videos"])
    assert "https://instagram.com/ghostbrand" in body["records"][0]["data"]["social_links"]
    assert "diagnostics" in body

    app.dependency_overrides.clear()


def test_jobs_scrape_endpoint_falls_back_when_playwright_missing(monkeypatch):
    orchestrator = ScrapeOrchestrator(
        static_fetcher=FakeStaticFetcher(),
        dynamic_fetcher=FakeDynamicFetcherMissingBrowser(),
        search_provider=FakeSearchProvider(),
    )

    async def fake_robots(url: str, user_agent: str = "*"):
        return True

    monkeypatch.setattr("app.services.scrape_orchestrator.robots_allows", fake_robots)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator

    client = TestClient(app)
    payload = {
        "query": "pull all images, videos, and social media assets for this creator campaign",
        "max_pages": 1,
        "mode": "auto",
    }

    response = client.post("/api/v1/jobs/scrape", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["stats"]["pages_processed"] == 1
    assert any(w["code"] == "PLAYWRIGHT_MISSING_FALLBACK" for w in body["warnings"])
    assert body["diagnostics"] is not None

    app.dependency_overrides.clear()


def test_jobs_scrape_endpoint_media_query_prefers_topical_dog_candidate(monkeypatch):
    orchestrator = ScrapeOrchestrator(
        static_fetcher=FakeStaticFetcher(),
        dynamic_fetcher=FakeDynamicFetcher(),
        search_provider=FakeSearchProviderDogQuery(),
    )

    async def fake_robots(url: str, user_agent: str = "*"):
        return True

    monkeypatch.setattr("app.services.scrape_orchestrator.robots_allows", fake_robots)
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator

    client = TestClient(app)
    payload = {
        "query": "top dog video",
        "max_pages": 1,
        "mode": "static",
    }

    response = client.post("/api/v1/jobs/scrape", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["records"][0]["record_type"] == "media"
    assert "dog" in body["records"][0]["source_url"]

    app.dependency_overrides.clear()
