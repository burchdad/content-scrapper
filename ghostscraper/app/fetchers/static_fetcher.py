import time

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models.fetch import FetchedPage


class StaticFetcher:
    def __init__(self, timeout_seconds: int = 30, retries: int = 2, user_agent: str = "GhostScraper/1.0") -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.user_agent = user_agent

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def fetch(self, url: str) -> FetchedPage:
        started = time.perf_counter()
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)

        content_type = response.headers.get("content-type", "")
        html: str | None = None
        if "text/html" in content_type or "application/xhtml+xml" in content_type:
            html = response.text

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response_headers = dict(response.headers)
        response_headers["x-fetch-ms"] = str(elapsed_ms)

        return FetchedPage(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            html=html,
            content_type=content_type or None,
            mode="static",
            response_headers=response_headers,
            rendered=False,
        )
