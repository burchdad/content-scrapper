import pytest
import respx

from app.discovery.search_provider import (
    BingHtmlSearchProvider,
    CompositeSearchProvider,
    DuckDuckGoHtmlSearchProvider,
    GoogleHtmlSearchProvider,
    YahooHtmlSearchProvider,
)


@pytest.mark.asyncio
async def test_duckduckgo_provider_extracts_result_urls():
    provider = DuckDuckGoHtmlSearchProvider(timeout_seconds=5)
    html = """
    <html><body>
      <a class='result__a' href='https://example.com/a'>Result A</a>
      <a class='result__a' href='https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb'>Result B</a>
    </body></html>
    """

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://duckduckgo.com/html/").respond(200, text=html)
        results = await provider.search("query", limit=5)

    urls = [r["url"] for r in results]
    assert "https://example.com/a" in urls
    assert "https://example.org/b" in urls


@pytest.mark.asyncio
async def test_bing_provider_extracts_result_urls():
    provider = BingHtmlSearchProvider(timeout_seconds=5)
    html = """
    <html><body>
      <li class='b_algo'><h2><a href='https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLm5ldC9h'>Result A</a></h2></li>
      <li class='b_algo'><h2><a href='/search?ignored=1'>Ignored</a></h2></li>
    </body></html>
    """

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://www.bing.com/search").respond(200, text=html)
        results = await provider.search("query", limit=5)

    assert results[0]["url"] == "https://example.net/a"
    assert results[0]["source"] == "bing_html"


@pytest.mark.asyncio
async def test_composite_provider_falls_back_when_first_empty():
    class EmptyProvider:
        async def search(self, query: str, limit: int = 10) -> list[dict]:
            return []

    class GoodProvider:
        async def search(self, query: str, limit: int = 10) -> list[dict]:
            return [{"url": "https://example.com/fallback", "title": "Fallback", "source": "good"}]

    provider = CompositeSearchProvider([EmptyProvider(), GoodProvider()])
    results = await provider.search("query", limit=5)

    assert results == [{"url": "https://example.com/fallback", "title": "Fallback", "source": "good"}]


@pytest.mark.asyncio
async def test_composite_provider_continues_when_provider_raises():
    class FailingProvider:
        async def search(self, query: str, limit: int = 10) -> list[dict]:
            raise RuntimeError("network timeout")

    class GoodProvider:
        async def search(self, query: str, limit: int = 10) -> list[dict]:
            return [{"url": "https://example.com/recovered", "title": "Recovered", "source": "good"}]

    provider = CompositeSearchProvider([FailingProvider(), GoodProvider()])
    results = await provider.search("query", limit=5)

    assert results == [{"url": "https://example.com/recovered", "title": "Recovered", "source": "good"}]


@pytest.mark.asyncio
async def test_google_provider_extracts_result_urls():
        provider = GoogleHtmlSearchProvider(timeout_seconds=5)
        html = """
        <html><body>
            <a href='/url?q=https://example.org/google-result&sa=U&ved=1'><h3>Google Result</h3></a>
        </body></html>
        """

        with respx.mock(assert_all_called=True) as mock:
                mock.get("https://www.google.com/search").respond(200, text=html)
                results = await provider.search("query", limit=5)

        assert results[0]["url"] == "https://example.org/google-result"
        assert results[0]["source"] == "google_html"


@pytest.mark.asyncio
async def test_yahoo_provider_extracts_result_urls():
        provider = YahooHtmlSearchProvider(timeout_seconds=5)
        html = """
        <html><body>
            <div id='web'><h3><a href='https://example.org/yahoo-result'>Yahoo Result</a></h3></div>
        </body></html>
        """

        with respx.mock(assert_all_called=True) as mock:
                mock.get("https://search.yahoo.com/search").respond(200, text=html)
                results = await provider.search("query", limit=5)

        assert results[0]["url"] == "https://example.org/yahoo-result"
        assert results[0]["source"] == "yahoo_html"
