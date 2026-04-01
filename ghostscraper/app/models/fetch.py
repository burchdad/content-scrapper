from pydantic import BaseModel


class FetchedPage(BaseModel):
    url: str
    final_url: str
    status_code: int
    html: str | None
    content_type: str | None
    mode: str
    response_headers: dict[str, str]
    rendered: bool = False
    image_candidates: list[str] = []
    video_candidates: list[str] = []
    discovered_links: list[str] = []


class BrowserFetchOptions(BaseModel):
    timeout_ms: int = 30000
    wait_until: str = "networkidle"
    auto_scroll: bool = True
    click_galleries: bool = False
    screenshot_on_failure: bool = False
    user_agent: str | None = None
