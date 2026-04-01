from typing import Any

from pydantic import BaseModel


class ScrapedRecord(BaseModel):
    source_url: str
    canonical_url: str | None = None
    record_type: str
    title: str | None = None
    data: dict[str, Any]
    images: list[str] = []
    videos: list[str] = []
    downloaded_images: list[str] = []
    confidence: float | None = None
    extraction_notes: list[str] = []
