from typing import Literal

from pydantic import BaseModel


class ExtractionField(BaseModel):
    name: str
    field_type: Literal["string", "number", "url", "email", "phone", "image_list", "object", "array"]
    required: bool = False


class ScrapePlan(BaseModel):
    intent: Literal["contacts", "products", "real_estate", "articles", "pricing", "media", "generic"]
    strategy: Literal["direct_static", "direct_dynamic", "search_then_scrape", "hybrid"]
    fields: list[ExtractionField]
    candidate_queries: list[str] = []
    target_urls: list[str] = []
    extraction_hints: list[str] = []
    use_playwright: bool = False
    paginate: bool = True
    click_galleries: bool = False
    capture_images: bool = True
