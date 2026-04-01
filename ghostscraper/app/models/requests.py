from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class ScrapeRequest(BaseModel):
    query: str = Field(..., description="Natural-language description of content to collect")
    websites: list[HttpUrl] | None = Field(default=None, description="Optional target sites")
    source_pack_ids: list[str] | None = Field(default=None, description="Optional curated source pack identifiers")
    output_format: Literal["json", "csv"] = "json"
    mode: Literal["auto", "static", "dynamic"] = "auto"
    max_pages: int = 10
    max_depth: int = 1
    include_images: bool = True
    include_videos: bool = True
    include_mature_content: bool = False
    download_images: bool = False
    image_limit_per_record: int = 20
    video_limit_per_record: int = 20
    paginate: bool = True
    follow_internal_links: bool = False
    use_search_discovery: bool = True
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    desired_fields: list[str] | None = None
    custom_schema: dict[str, Any] | None = None
    timeout_seconds: int = 30
    retries: int = 2
    respect_robots_txt: bool = True
    user_agent: str | None = None
