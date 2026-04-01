from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright


@asynccontextmanager
async def browser_context(headless: bool = True, user_agent: str | None = None) -> AsyncIterator[tuple]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1366, "height": 900},
        )
        try:
            yield browser, context
        finally:
            await context.close()
            await browser.close()
