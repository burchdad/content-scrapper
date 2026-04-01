import uuid
from datetime import UTC, datetime
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.ingesters.courtlistener import CourtListenerIngester
from app.ingesters.fbi import ALL_LIST_NAMES, FBIIngester
from app.ingesters.gdelt import GDELTIngester
from app.ingesters.interpol import InterpolIngester
from app.ingesters.namus import NamUsIngester
from app.ingesters.ncmec import NCMECIngester
from app.ingesters.newsapi import NewsAPIIngester
from app.ingesters.polaris import PolarisIngester
from app.models.case import Case
from app.models.schemas import IngestRequest, IngestResponse
from app.services.ai_signal_enrichment import AISignalEnrichmentService
from app.services.case_priority_service import CasePriorityService
from app.services.entity_memory_service import EntityMemoryService
from app.services.entity_resolution.resolver import EntityResolver
from app.services.source_registry import get_trust_level, is_source_approved, requires_staging

router = APIRouter(prefix="/api/v1", tags=["ingestion"])
settings = get_settings()


def _documents_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "documents"


def _documents_index_path() -> Path:
    return _documents_root() / "index.json"


def _load_documents_index() -> list[dict]:
    path = _documents_index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        return []
    return []


def _save_documents_index(rows: list[dict]) -> None:
    path = _documents_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _safe_filename(name: str) -> str:
    out: list[str] = []
    for ch in name:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("-")
    safe = "".join(out).strip(".-")
    return safe or "document"


class NamUsImportRequest(BaseModel):
    data_file: str | None = None
    live: bool = False
    pages: int = 1
    per_page: int = 25
    fetch_details: bool = True
    case_set: str = "MissingPersons"
    last_name: str | None = None
    first_name: str | None = None
    case_number: str | None = None
    city: str | None = None
    state: str | None = None


@router.post("/ingest", response_model=IngestResponse)
async def ingest_records(
    request: IngestRequest,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """
    Ingest entity records from public/permitted sources.

    Runs synchronous entity resolution for each entity payload.
    For large batches (>50 entities), use POST /ingest/async to queue via Celery.

    **All sources must be public and legally permitted.**
    """
    # --- Source Gatekeeper ---
    # Determine the effective source name for the batch
    effective_source = request.source_name
    if effective_source == "unknown":
        # Peek at first entity for a non-unknown source
        if request.entities and request.entities[0].source_name != "unknown":
            effective_source = request.entities[0].source_name

    if not is_source_approved(effective_source):
        if requires_staging(effective_source):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "source_not_approved_for_direct_ingest",
                    "source": effective_source,
                    "message": (
                        f"Source '{effective_source}' must pass through the staging layer "
                        "before entering GhostRescue. "
                        "Submit to POST /api/v1/staging/submit instead."
                    ),
                    "staging_endpoint": "/api/v1/staging/submit",
                },
            )
        # Unknown source without a staging path
        raise HTTPException(
            status_code=403,
            detail={
                "error": "unknown_source",
                "source": effective_source,
                "message": (
                    f"Source '{effective_source}' is not in the approved source registry. "
                    "Use POST /api/v1/staging/sources to view approved sources."
                ),
            },
        )

    resolver = EntityResolver(db)
    memory = EntityMemoryService(db)
    resolved_entity_ids: list[str] = []
    for entity_payload in request.entities:
        # Inherit top-level source_name if not set per-entity
        if entity_payload.source_name == "unknown" and request.source_name != "unknown":
            entity_payload.source_name = request.source_name
        result = await resolver.resolve(entity_payload)
        resolved_entity_ids.append(result.entity_id)
        await memory.record_event(
            entity_id=result.entity_id,
            event_type="ingested",
            summary=f"Entity payload ingested from source '{entity_payload.source_name}'.",
            source_name=entity_payload.source_name,
            source_url=request.source_url,
            metadata={"action": result.action, "match_score": result.match_score},
        )

    return IngestResponse(
        job_id=f"ingest-{uuid.uuid4().hex[:10]}",
        status="processed",
        entities_queued=len(request.entities),
        resolved_entity_ids=resolved_entity_ids,
        disclaimer=settings.disclaimer,
    )


@router.post("/ingest/namus")
async def ingest_namus_records(
    request: NamUsImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest NamUs records from the live public registry or a local file."""
    valid_case_sets = {"MissingPersons", "UnidentifiedPersons", "UnclaimedPersons"}
    if request.case_set not in valid_case_sets:
        return {
            "status": "rejected",
            "reason": f"case_set must be one of {sorted(valid_case_sets)}",
            "disclaimer": settings.disclaimer,
        }
    if request.live:
        ingester = NamUsIngester(
            db,
            case_set=request.case_set,
            live=True,
            pages=request.pages,
            per_page=request.per_page,
            fetch_details=request.fetch_details,
            last_name=request.last_name,
            first_name=request.first_name,
            case_number=request.case_number,
            city=request.city,
            state=request.state,
        )
    else:
        project_root = Path(__file__).resolve().parents[2]
        default_path = project_root / "sample_data" / "namus_missing_persons.json"

        requested = Path(request.data_file).expanduser() if request.data_file else default_path
        if not requested.is_absolute():
            requested = (project_root / requested).resolve()

        # Restrict file access to project directory for safety.
        if not str(requested).startswith(str(project_root.resolve())):
            return {
                "status": "rejected",
                "reason": "data_file must be inside the project workspace",
                "disclaimer": settings.disclaimer,
            }

        ingester = NamUsIngester(db, data_file=str(requested))

    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["namus_*"],
        max_records=20,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "namus",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


class InterpolImportRequest(BaseModel):
    data_file: str | None = None
    live: bool = False
    pages: int = 1
    fetch_details: bool = True


class NewsAPIImportRequest(BaseModel):
    api_key: str | None = None


class FBIImportRequest(BaseModel):
    lists: list[str] | None = None   # None = default mission-relevant lists
    pages: int = 10
    per_page: int = 50


class CourtListenerImportRequest(BaseModel):
    api_token: str | None = None
    queries: list[str] | None = None
    pages_per_query: int = 2
    page_size: int = 20
    ai_enrich: bool = True
    ai_max_records: int = 25


class PolarisImportRequest(BaseModel):
    data_file: str | None = None
    sitemap_url: str | None = None
    seed_urls: list[str] | None = None
    max_pages: int = 40


class GDELTImportRequest(BaseModel):
    queries: list[str] | None = None
    max_records_per_query: int = 25
    timespan: str = "7d"


class NCMECImportRequest(BaseModel):
    data_file: str | None = None
    live: bool = True
    pages: int = 1
    search: str = ""


async def _run_post_ingest_ai_enrichment(
    db: AsyncSession,
    *,
    source_patterns: list[str],
    max_records: int = 20,
) -> dict:
    service = AISignalEnrichmentService(
        db,
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
    if not service.enabled:
        return {
            "enabled": False,
            "provider": None,
            "targeted": 0,
            "enriched": 0,
        }

    result = await service.enrich_recent_signals(
        source_patterns=source_patterns,
        max_records=max_records,
    )
    await db.commit()
    return result


async def _warm_priority_cache(db: AsyncSession, *, recent_limit: int = 40) -> dict:
    """Warm corroboration cache for recently updated cases after source ingestion."""
    recent_cases = (
        await db.scalars(
            select(Case)
            .order_by(Case.updated_at.desc())
            .limit(max(5, min(recent_limit, 120)))
        )
    ).all()
    if not recent_cases:
        return {"warmed": 0}
    scored = await CasePriorityService(db).score_cases(recent_cases, apply_saturation=True)
    return {"warmed": len(scored)}


@router.post("/ingest/interpol")
async def ingest_interpol_records(
    request: InterpolImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest INTERPOL Red Notice records.

    Two modes:
    - ``live=true``  — Fetches directly from ws-public.interpol.int.
                       Control volume with ``pages`` (20 records/page) and
                       ``fetch_details`` (enriches each record with charge data).
    - ``live=false`` — Reads a local JSON/CSV file (``data_file`` param or
                       default sample). Accepts raw API dumps or simplified lists.
    """
    if request.live:
        ingester = InterpolIngester(
            db,
            live=True,
            pages=request.pages,
            fetch_details=request.fetch_details,
        )
    else:
        project_root = Path(__file__).resolve().parents[2]
        default_path = project_root / "sample_data" / "interpol_red_notices.json"

        requested = Path(request.data_file).expanduser() if request.data_file else default_path
        if not requested.is_absolute():
            requested = (project_root / requested).resolve()

        # Restrict file access to project directory for safety.
        if not str(requested).startswith(str(project_root.resolve())):
            return {
                "status": "rejected",
                "reason": "data_file must be inside the project workspace",
                "disclaimer": settings.disclaimer,
            }

        ingester = InterpolIngester(db, data_file=str(requested))

    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["interpol"],
        max_records=20,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "interpol",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/newsapi")
async def ingest_newsapi_records(
    request: NewsAPIImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest trafficking-related news articles from NewsAPI."""
    ingester = NewsAPIIngester(db, api_key=request.api_key)
    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["newsapi-*"],
        max_records=20,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "newsapi",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/fbi")
async def ingest_fbi_records(
    request: FBIImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest records from the public FBI Most Wanted API (no key required).

    ``lists``    — list of FBI list names to include (default: kidnap,
                   parental_kidnap, vicap_missing, topten, fugitives,
                   criminal_enterprise).  Pass an empty list to use defaults.
    ``pages``    — number of API pages to fetch (50 records/page).
    ``per_page`` — records per API request (max 50).

    Valid list names: kidnap, parental_kidnap, vicap_missing, vicap_homicide,
    topten, fugitives, criminal_enterprise, murders, terrorism, lea, seeking_info.
    """
    if request.lists is not None:
        invalid = set(request.lists) - ALL_LIST_NAMES
        if invalid:
            return {
                "status": "rejected",
                "reason": f"Unknown list name(s): {sorted(invalid)}. Valid: {sorted(ALL_LIST_NAMES)}",
                "disclaimer": settings.disclaimer,
            }

    ingester = FBIIngester(
        db,
        lists=request.lists or None,
        pages=request.pages,
        per_page=request.per_page,
    )
    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["fbi most wanted"],
        max_records=25,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "fbi_wanted",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/courtlistener")
async def ingest_courtlistener_records(
    request: CourtListenerImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest legal reference records from CourtListener REST Search API.

    Uses token authentication with the configured ``COURTLISTENER_API_TOKEN``
    by default, or an explicit ``api_token`` in the request body.
    """
    ingester = CourtListenerIngester(
        db,
        api_token=request.api_token or settings.courtlistener_api_token,
        queries=request.queries,
        pages_per_query=request.pages_per_query,
        page_size=request.page_size,
        ai_enrich=request.ai_enrich,
        ai_max_records=request.ai_max_records,
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
    result = await ingester.ingest()
    if not (result.get("ai_enabled") and result.get("ai_enriched_count", 0) > 0):
        ai_result = await _run_post_ingest_ai_enrichment(
            db,
            source_patterns=["courtlistener"],
            max_records=request.ai_max_records,
        )
        result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "courtlistener",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/polaris")
async def ingest_polaris_records(
    request: PolarisImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest Polaris Project content via live HTML or local JSON file."""
    if request.data_file:
        project_root = Path(__file__).resolve().parents[2]
        requested = Path(request.data_file).expanduser()
        if not requested.is_absolute():
            requested = (project_root / requested).resolve()
        if not str(requested).startswith(str(project_root.resolve())):
            return {
                "status": "rejected",
                "reason": "data_file must be inside the project workspace",
                "disclaimer": settings.disclaimer,
            }
        data_file = str(requested)
    else:
        data_file = None

    ingester = PolarisIngester(
        db,
        sitemap_url=request.sitemap_url or "https://polarisproject.org/sitemap.xml",
        seed_urls=request.seed_urls,
        max_pages=request.max_pages,
        data_file=data_file,
    )
    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["polaris_project"],
        max_records=25,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "polaris_project",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/gdelt")
async def ingest_gdelt_records(
    request: GDELTImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest GDELT DOC API article leads (v2 doc endpoint)."""
    ingester = GDELTIngester(
        db,
        queries=request.queries,
        max_records_per_query=request.max_records_per_query,
        timespan=request.timespan,
    )
    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["gdelt"],
        max_records=25,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "gdelt",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/ncmec")
async def ingest_ncmec_records(
    request: NCMECImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest NCMEC missing-child poster leads from public search endpoint or local file."""
    data_file: str | None = None
    if request.data_file:
        project_root = Path(__file__).resolve().parents[2]
        requested = Path(request.data_file).expanduser()
        if not requested.is_absolute():
            requested = (project_root / requested).resolve()
        if not str(requested).startswith(str(project_root.resolve())):
            return {
                "status": "rejected",
                "reason": "data_file must be inside the project workspace",
                "disclaimer": settings.disclaimer,
            }
        data_file = str(requested)

    ingester = NCMECIngester(
        db,
        data_file=data_file,
        live=request.live,
        pages=request.pages,
        search=request.search,
    )
    result = await ingester.ingest()
    ai_result = await _run_post_ingest_ai_enrichment(
        db,
        source_patterns=["ncmec"],
        max_records=25,
    )
    result["ai_enrichment"] = ai_result
    result["priority_cache_warm"] = await _warm_priority_cache(db)

    return {
        "status": "processed" if not result.get("skipped") else "skipped",
        "source": "ncmec",
        "result": result,
        "disclaimer": settings.disclaimer,
    }


@router.post("/ingest/documents")
async def ingest_documents(
    files: list[UploadFile] = File(...),
    case_id: str | None = Form(default=None),
    source_name: str = Form(default="analyst_upload"),
    notes: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import analyst documents into the evidence workspace and optionally link them to a case."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    linked_case = None
    if case_id:
        linked_case = await db.scalar(select(Case).where(Case.case_id == case_id))
        if not linked_case:
            raise HTTPException(status_code=404, detail="Case not found for document link")

    now = datetime.now(UTC)
    date_folder = now.strftime("%Y-%m-%d")
    day_dir = _documents_root() / date_folder
    day_dir.mkdir(parents=True, exist_ok=True)

    index = _load_documents_index()
    imported: list[dict] = []

    for up in files:
        original_name = up.filename or "document"
        safe_name = _safe_filename(original_name)
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        stored_name = f"{doc_id}-{safe_name}"
        stored_path = day_dir / stored_name
        payload = await up.read()
        stored_path.write_bytes(payload)

        row = {
            "doc_id": doc_id,
            "file_name": original_name,
            "stored_path": str(stored_path),
            "size_bytes": len(payload),
            "content_type": up.content_type or "application/octet-stream",
            "case_id": case_id,
            "source_name": source_name,
            "notes": notes,
            "imported_at": now.isoformat(),
        }
        imported.append(row)
        index.append(row)

    _save_documents_index(index)

    if linked_case:
        meta = dict(linked_case.extra_metadata or {})
        existing = meta.get("document_ids")
        if not isinstance(existing, list):
            existing = []
        existing.extend([d["doc_id"] for d in imported])
        meta["document_ids"] = sorted(set(existing))
        meta["document_count"] = len(meta["document_ids"])
        linked_case.extra_metadata = meta
        linked_case.updated_at = now
        await db.commit()

    return {
        "status": "processed",
        "imported_count": len(imported),
        "documents": imported,
        "linked_case_id": case_id,
        "disclaimer": settings.disclaimer,
    }


@router.get("/ingest/documents")
async def list_ingested_documents(
    case_id: str | None = None,
    date: str | None = None,
    limit: int = 100,
) -> dict:
    rows = _load_documents_index()
    out = rows
    if case_id:
        out = [r for r in out if r.get("case_id") == case_id]
    if date:
        out = [r for r in out if str(r.get("imported_at") or "").startswith(date)]
    out = sorted(out, key=lambda r: str(r.get("imported_at") or ""), reverse=True)
    out = out[: max(1, min(limit, 500))]
    return {
        "total": len(out),
        "documents": out,
    }


@router.get("/ingest/documents/{doc_id}/download")
async def download_ingested_document(doc_id: str) -> FileResponse:
    rows = _load_documents_index()
    match = next((r for r in rows if r.get("doc_id") == doc_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(match.get("stored_path") or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Stored document missing")
    return FileResponse(path=str(path), filename=match.get("file_name") or path.name)
