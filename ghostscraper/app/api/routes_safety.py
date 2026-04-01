from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.config import Settings, get_settings
from app.models.safety import (
    SafetyCase,
    SafetyCaseBulkWorkflowUpdateRequest,
    SafetyCaseBulkWorkflowUpdateResult,
    SafetyCaseCreateFromJobRequest,
    SafetyCaseReportPackage,
    SafetyCaseReportSignoff,
    SafetyCaseReportWorkflowState,
    SafetyCaseReportWorkflowUpdateRequest,
    SafetyCaseSummary,
    SafetyPersonaSpec,
)
from app.services.safety_case_service import SafetyCaseService
from app.services.safety_persona_service import SafetyPersonaService
from app.services.state_service import StateService

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


def get_state_service(settings: Settings = Depends(get_settings)) -> StateService:
    return StateService(settings.storage_root)


def get_safety_service(settings: Settings = Depends(get_settings)) -> SafetyCaseService:
    return SafetyCaseService(settings.storage_root)


def get_safety_persona_service() -> SafetyPersonaService:
    return SafetyPersonaService()


@router.post("/cases/from-job", response_model=SafetyCase)
async def create_case_from_job(
    request: SafetyCaseCreateFromJobRequest,
    state: StateService = Depends(get_state_service),
    safety: SafetyCaseService = Depends(get_safety_service),
) -> SafetyCase:
    job = state.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return safety.create_case_from_job(job, request)


@router.get("/cases", response_model=list[SafetyCaseSummary])
async def list_cases(
    limit: int = Query(default=20, ge=1, le=200),
    signoff_approved: bool | None = Query(default=None),
    destination_channel: str | None = Query(default=None),
    safety: SafetyCaseService = Depends(get_safety_service),
) -> list[SafetyCaseSummary]:
    return safety.list_cases(
        limit=limit,
        signoff_approved=signoff_approved,
        destination_channel=destination_channel,
    )


@router.get("/cases/export.csv")
async def export_case_summaries_csv(
    limit: int = Query(default=200, ge=1, le=2000),
    signoff_approved: bool | None = Query(default=None),
    destination_channel: str | None = Query(default=None),
    safety: SafetyCaseService = Depends(get_safety_service),
) -> Response:
    summaries = safety.list_cases(
        limit=limit,
        signoff_approved=signoff_approved,
        destination_channel=destination_channel,
    )
    csv_payload = safety.case_summaries_csv(summaries)
    return Response(
        content=csv_payload,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="safety-cases-summary.csv"'},
    )


@router.get("/cases/{case_id}", response_model=SafetyCase)
async def get_case(case_id: str, safety: SafetyCaseService = Depends(get_safety_service)) -> SafetyCase:
    case = safety.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/cases/{case_id}/report", response_model=SafetyCaseReportPackage)
async def get_case_report_package(
    case_id: str,
    reviewer: str | None = Query(default=None),
    safety: SafetyCaseService = Depends(get_safety_service),
) -> SafetyCaseReportPackage:
    case = safety.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return safety.build_case_report_package(case=case, reviewer=reviewer)


@router.patch("/cases/{case_id}/report/workflow", response_model=SafetyCaseReportWorkflowState)
async def update_case_report_workflow(
    case_id: str,
    request: SafetyCaseReportWorkflowUpdateRequest,
    safety: SafetyCaseService = Depends(get_safety_service),
) -> SafetyCaseReportWorkflowState:
    case = safety.update_case_report_workflow(case_id=case_id, request=request)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return SafetyCaseReportWorkflowState(
        case_id=case.case_id,
        submission_checklist=case.submission_checklist,
        signoff=case.signoff or SafetyCaseReportSignoff(),
    )


@router.patch("/cases/report/workflow/bulk", response_model=SafetyCaseBulkWorkflowUpdateResult)
async def bulk_update_case_report_workflow(
    request: SafetyCaseBulkWorkflowUpdateRequest,
    safety: SafetyCaseService = Depends(get_safety_service),
) -> SafetyCaseBulkWorkflowUpdateResult:
    return safety.bulk_update_case_report_workflow(case_ids=request.case_ids, request=request.workflow)


@router.get("/cases/{case_id}/report.json")
async def download_case_report_package(
    case_id: str,
    reviewer: str | None = Query(default=None),
    safety: SafetyCaseService = Depends(get_safety_service),
) -> Response:
    case = safety.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    package = safety.build_case_report_package(case=case, reviewer=reviewer)
    payload = safety.report_package_json(package)
    filename = f"safety-case-{case.case_id}-report.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/persona", response_model=SafetyPersonaSpec)
async def get_safety_persona(
    persona_service: SafetyPersonaService = Depends(get_safety_persona_service),
) -> SafetyPersonaSpec:
    return persona_service.get_default_persona()
