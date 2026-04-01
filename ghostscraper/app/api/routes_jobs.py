from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.core.config import Settings, get_settings
from app.discovery.search_provider import build_search_provider
from app.models.requests import ScrapeRequest
from app.models.responses import AsyncJobAccepted, JobListPage, JobRecordsPage, JobRunSummary, JobSummary, ScrapeResponse
from app.outputs.exporters import render_csv
from app.services.async_job_queue import AsyncJobQueue
from app.services.scrape_orchestrator import ScrapeOrchestrator
from app.services.state_service import StateService
from app.services.source_pack_service import SourcePackService

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def get_orchestrator(settings: Settings = Depends(get_settings)) -> ScrapeOrchestrator:
    return ScrapeOrchestrator(storage_root=settings.storage_root, search_provider=build_search_provider(settings))


def get_state_service(settings: Settings = Depends(get_settings)) -> StateService:
    return StateService(settings.storage_root)


def get_job_queue(request: Request) -> AsyncJobQueue:
    return request.app.state.job_queue


def get_source_pack_service() -> SourcePackService:
    return SourcePackService()


def _validate_source_packs(request: ScrapeRequest, service: SourcePackService) -> None:
    unknown = service.unknown_pack_ids(request.source_pack_ids)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown source packs: {', '.join(unknown)}")


def _parse_fields(fields: str | None) -> list[str] | None:
    if not fields:
        return None
    parsed = [field.strip() for field in fields.split(",") if field.strip()]
    return parsed or None


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_job(
    request: ScrapeRequest,
    orchestrator: ScrapeOrchestrator = Depends(get_orchestrator),
    state: StateService = Depends(get_state_service),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> ScrapeResponse:
    _validate_source_packs(request, source_packs)
    response = await orchestrator.run_scrape_job(request)
    state.save_job(response)
    return response


@router.post("/scrape/async", response_model=AsyncJobAccepted)
async def scrape_job_async(
    request: ScrapeRequest,
    queue: AsyncJobQueue = Depends(get_job_queue),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> AsyncJobAccepted:
    _validate_source_packs(request, source_packs)
    job_id = await queue.enqueue(request)
    return AsyncJobAccepted(job_id=job_id, status="queued")


@router.get("", response_model=JobListPage)
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    status: Literal["queued", "running", "completed", "failed"] | None = None,
    cursor: str | None = Query(default=None),
    state: StateService = Depends(get_state_service),
) -> JobListPage:
    try:
        items, next_cursor = state.list_jobs_page(limit=limit, status=status, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summaries = [
        JobSummary(
            job_id=job.job_id,
            status=job.status,
            records_extracted=int(job.stats.get("records_extracted", 0)),
            pages_processed=int(job.stats.get("pages_processed", 0)),
            failures=int(job.stats.get("failures", 0)),
            elapsed_ms=int(job.stats.get("elapsed_ms", 0)),
            updated_at=updated_at,
        )
        for job, updated_at in items
    ]
    return JobListPage(items=summaries, next_cursor=next_cursor)


@router.get("/{job_id}/records", response_model=JobRecordsPage)
async def get_job_records(
    job_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    fields: str | None = Query(default=None),
    state: StateService = Depends(get_state_service),
) -> JobRecordsPage:
    requested_fields = _parse_fields(fields)
    response, items, total, has_more = state.get_job_records_page(
        job_id=job_id,
        limit=limit,
        offset=offset,
        fields=requested_fields,
    )
    if not response:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobRecordsPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
        requested_fields=requested_fields,
    )


@router.get("/{job_id}/export.csv")
async def export_job_csv(
    job_id: str,
    fields: str | None = Query(default=None),
    state: StateService = Depends(get_state_service),
) -> Response:
    requested_fields = _parse_fields(fields)
    response, items = state.get_all_job_records(job_id=job_id, fields=requested_fields)
    if not response:
        raise HTTPException(status_code=404, detail="Job not found")

    csv_text = render_csv(items)
    headers = {"Content-Disposition": f'attachment; filename="{job_id}.csv"'}
    return Response(content=csv_text, media_type="text/csv", headers=headers)


@router.get("/{job_id}", response_model=ScrapeResponse)
async def get_job(job_id: str, state: StateService = Depends(get_state_service)) -> ScrapeResponse:
    response = state.get_job(job_id)
    if not response:
        raise HTTPException(status_code=404, detail="Job not found")
    return response


@router.get("/{job_id}/summary", response_model=JobRunSummary)
async def get_job_summary(job_id: str, state: StateService = Depends(get_state_service)) -> JobRunSummary:
    response = state.get_job(job_id)
    if not response:
        raise HTTPException(status_code=404, detail="Job not found")

    stats = response.stats or {}
    pages_processed = int(stats.get("pages_processed", 0))
    records_extracted = int(stats.get("records_extracted", 0))
    failures = int(stats.get("failures", 0))
    elapsed_ms = int(stats.get("elapsed_ms", 0))

    intent = response.plan.get("intent") if isinstance(response.plan, dict) else None
    strategy = response.plan.get("strategy") if isinstance(response.plan, dict) else None

    diagnostics = response.diagnostics
    primary_issue = diagnostics.primary_issue if diagnostics else None
    recommendation = diagnostics.recommendation if diagnostics else None
    warning_counts = diagnostics.warning_counts if diagnostics else {}

    if response.status in {"queued", "running"}:
        headline = f"Job is {response.status}. Processing has not finished yet."
    elif records_extracted > 0:
        headline = f"Extracted {records_extracted} records from {pages_processed} pages."
    elif primary_issue:
        headline = f"No records extracted. Primary issue: {primary_issue}."
    else:
        headline = "No records extracted. Check warnings for details."

    sample_source_urls = [record.source_url for record in response.records[:5]]

    return JobRunSummary(
        job_id=response.job_id,
        status=response.status,
        intent=intent,
        strategy=strategy,
        headline=headline,
        records_extracted=records_extracted,
        pages_processed=pages_processed,
        failures=failures,
        elapsed_ms=elapsed_ms,
        primary_issue=primary_issue,
        recommendation=recommendation,
        warning_counts=warning_counts,
        sample_source_urls=sample_source_urls,
    )
