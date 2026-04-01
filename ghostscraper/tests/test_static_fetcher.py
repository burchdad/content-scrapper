import pytest
import respx
from httpx import Response

from app.fetchers.static_fetcher import StaticFetcher


@pytest.mark.asyncio
async def test_static_fetcher_returns_html_payload():
    fetcher = StaticFetcher(timeout_seconds=5)
    html = "<html><body><h1>Hello</h1></body></html>"

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://example.com").respond(200, text=html, headers={"content-type": "text/html"})
        result = await fetcher.fetch("https://example.com")

    assert result.status_code == 200
    assert result.html is not None
    assert "Hello" in result.html
    assert result.mode == "static"
