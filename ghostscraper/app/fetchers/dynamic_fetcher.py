from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.fetchers.browser_session import browser_context
from app.models.fetch import BrowserFetchOptions, FetchedPage


class DynamicFetcher:
    GALLERY_TERMS = ["photos", "gallery", "see all", "view more"]

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    async def fetch(self, url: str, options: BrowserFetchOptions) -> FetchedPage:
        network_images: list[str] = []
        network_videos: list[str] = []
        try:
            async with browser_context(headless=self.headless, user_agent=options.user_agent) as (_, context):
                page = await context.new_page()

                page.on(
                    "response",
                    lambda resp: network_images.append(resp.url)
                    if any(ext in resp.url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", "/image", "/media"])
                    else None,
                )
                page.on(
                    "response",
                    lambda resp: network_videos.append(resp.url)
                    if any(ext in resp.url.lower() for ext in [".mp4", ".mov", ".m3u8", ".webm", "/video", "manifest"])
                    else None,
                )

                await page.goto(url, wait_until=options.wait_until, timeout=options.timeout_ms)
                if options.auto_scroll:
                    await self._auto_scroll(page)
                if options.click_galleries:
                    await self._click_gallery_candidates(page)

                html = await page.content()
                dom_images = await self._collect_images(page)
                dom_videos = await self._collect_videos(page)

                return FetchedPage(
                    url=url,
                    final_url=page.url,
                    status_code=200,
                    html=html,
                    content_type="text/html",
                    mode="dynamic",
                    response_headers={},
                    rendered=True,
                    image_candidates=list(dict.fromkeys(dom_images + network_images)),
                    video_candidates=list(dict.fromkeys(dom_videos + network_videos)),
                )
        except PlaywrightTimeoutError:
            return FetchedPage(
                url=url,
                final_url=url,
                status_code=408,
                html=None,
                content_type=None,
                mode="dynamic",
                response_headers={},
                rendered=True,
            )

    async def _auto_scroll(self, page) -> None:
        for _ in range(4):
            await page.mouse.wheel(0, 2000)
            await page.wait_for_timeout(350)

    async def _click_gallery_candidates(self, page) -> None:
        for term in self.GALLERY_TERMS:
            locator = page.get_by_role("button", name=term)
            if await locator.count() > 0:
                await locator.first.click(timeout=1500)
                await page.wait_for_timeout(250)

            link_locator = page.get_by_role("link", name=term)
            if await link_locator.count() > 0:
                await link_locator.first.click(timeout=1500)
                await page.wait_for_timeout(250)

    async def _collect_images(self, page) -> list[str]:
        nodes = await page.query_selector_all("img")
        results: list[str] = []
        for node in nodes:
            src = await node.get_attribute("src")
            current = await node.get_attribute("currentSrc")
            data_src = await node.get_attribute("data-src")
            srcset = await node.get_attribute("srcset")
            for value in [src, current, data_src]:
                if value:
                    results.append(urljoin(page.url, value))
            if srcset:
                for piece in srcset.split(","):
                    url = piece.strip().split(" ")[0]
                    if url:
                        results.append(urljoin(page.url, url))
        return list(dict.fromkeys(results))

    async def _collect_videos(self, page) -> list[str]:
        results: list[str] = []
        videos = await page.query_selector_all("video")
        for node in videos:
            src = await node.get_attribute("src")
            poster = await node.get_attribute("poster")
            if src:
                results.append(urljoin(page.url, src))
            if poster:
                results.append(urljoin(page.url, poster))

        sources = await page.query_selector_all("video source, audio source")
        for node in sources:
            src = await node.get_attribute("src")
            if src:
                results.append(urljoin(page.url, src))

        return list(dict.fromkeys(results))
