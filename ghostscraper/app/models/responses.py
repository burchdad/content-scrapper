from typing import Any

from pydantic import BaseModel

from app.models.records import ScrapedRecord


class JobWarning(BaseModel):
    code: str
    message: str
    url: str | None = None


class JobDiagnostics(BaseModel):
    primary_issue: str | None = None
    recommendation: str | None = None
    warning_counts: dict[str, int] = {}


class ScrapeResponse(BaseModel):
    job_id: str
    status: str
    plan: dict[str, Any]
    records: list[ScrapedRecord]
    stats: dict[str, Any]
    warnings: list[JobWarning] = []
    diagnostics: JobDiagnostics | None = None


class AsyncJobAccepted(BaseModel):
    job_id: str
    status: str = "queued"


class JobSummary(BaseModel):
    job_id: str
    status: str
    records_extracted: int = 0
    pages_processed: int = 0
    failures: int = 0
    elapsed_ms: int = 0
    updated_at: str


class JobListPage(BaseModel):
    items: list[JobSummary]
    next_cursor: str | None = None


class JobRecordsPage(BaseModel):
    items: list[ScrapedRecord]
    total: int
    limit: int
    offset: int
    has_more: bool
    requested_fields: list[str] | None = None


class JobRunSummary(BaseModel):
    job_id: str
    status: str
    intent: str | None = None
    strategy: str | None = None
    headline: str
    records_extracted: int = 0
    pages_processed: int = 0
    failures: int = 0
    elapsed_ms: int = 0
    primary_issue: str | None = None
    recommendation: str | None = None
    warning_counts: dict[str, int] = {}
    sample_source_urls: list[str] = []
