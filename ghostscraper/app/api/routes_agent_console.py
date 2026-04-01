from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.config import Settings, get_settings
from app.discovery.search_provider import build_search_provider
from app.models.agent_console import (
    AgentHistoryItem,
    AgentPreset,
    AgentPresetCreateRequest,
    AgentSafetyPresetRequest,
    AgentSubmitRequest,
    AgentSubmitResponse,
)
from app.services.agent_console_service import AgentConsoleService
from app.services.async_job_queue import AsyncJobQueue
from app.services.scrape_orchestrator import ScrapeOrchestrator
from app.services.state_service import StateService
from app.services.source_pack_service import SourcePackService

router = APIRouter(prefix="/api/v1/agent", tags=["agent-console"])


def get_agent_console_service(settings: Settings = Depends(get_settings)) -> AgentConsoleService:
    return AgentConsoleService(settings.storage_root)


def get_state_service(settings: Settings = Depends(get_settings)) -> StateService:
    return StateService(settings.storage_root)


def get_orchestrator(settings: Settings = Depends(get_settings)) -> ScrapeOrchestrator:
    return ScrapeOrchestrator(storage_root=settings.storage_root, search_provider=build_search_provider(settings))


def get_job_queue(request: Request) -> AsyncJobQueue:
    return request.app.state.job_queue


def get_source_pack_service() -> SourcePackService:
    return SourcePackService()


def _validate_source_packs(service: SourcePackService, request) -> None:
    unknown = service.unknown_pack_ids(request.request.source_pack_ids)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown source packs: {', '.join(unknown)}")


@router.get("/presets", response_model=list[AgentPreset])
async def list_presets(
    user_id: str = Query(default="default", min_length=1),
    service: AgentConsoleService = Depends(get_agent_console_service),
) -> list[AgentPreset]:
    return service.list_presets(user_id)


@router.post("/presets", response_model=AgentPreset)
async def create_preset(
    request: AgentPresetCreateRequest,
    service: AgentConsoleService = Depends(get_agent_console_service),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> AgentPreset:
    _validate_source_packs(source_packs, request)
    return service.create_preset(request)


@router.post("/presets/safety-default", response_model=AgentPreset)
async def create_safety_default_preset(
    request: AgentSafetyPresetRequest,
    service: AgentConsoleService = Depends(get_agent_console_service),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> AgentPreset:
    preset = service.create_safety_monitoring_preset(request)
    unknown = source_packs.unknown_pack_ids(preset.request.source_pack_ids)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown source packs: {', '.join(unknown)}")
    return preset


@router.delete("/presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    user_id: str = Query(default="default", min_length=1),
    service: AgentConsoleService = Depends(get_agent_console_service),
) -> dict:
    deleted = service.delete_preset(user_id=user_id, preset_id=preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"deleted": True}


@router.get("/history", response_model=list[AgentHistoryItem])
async def list_history(
    user_id: str = Query(default="default", min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: AgentConsoleService = Depends(get_agent_console_service),
) -> list[AgentHistoryItem]:
    return service.list_history(user_id=user_id, limit=limit, offset=offset)


@router.post("/history/submit", response_model=AgentSubmitResponse)
async def submit_request(
    submit: AgentSubmitRequest,
    service: AgentConsoleService = Depends(get_agent_console_service),
    state: StateService = Depends(get_state_service),
    orchestrator: ScrapeOrchestrator = Depends(get_orchestrator),
    queue: AsyncJobQueue = Depends(get_job_queue),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> AgentSubmitResponse:
    _validate_source_packs(source_packs, submit)
    if submit.run_async:
        job_id = await queue.enqueue(submit.request)
    else:
        response = await orchestrator.run_scrape_job(submit.request)
        state.save_job(response)
        job_id = response.job_id

    history_item = service.create_history_item(submit=submit, job_id=job_id)
    return AgentSubmitResponse(history_id=history_item.history_id, job_id=job_id, run_async=submit.run_async)


@router.delete("/history/{history_id}")
async def delete_history_item(
    history_id: str,
    user_id: str = Query(default="default", min_length=1),
    service: AgentConsoleService = Depends(get_agent_console_service),
) -> dict:
    deleted = service.delete_history_item(user_id=user_id, history_id=history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History item not found")
    return {"deleted": True}


@router.post("/history/{history_id}/rerun", response_model=AgentSubmitResponse)
async def rerun_history_item(
    history_id: str,
    user_id: str = Query(default="default", min_length=1),
    run_async: bool = Query(default=True),
    service: AgentConsoleService = Depends(get_agent_console_service),
    state: StateService = Depends(get_state_service),
    orchestrator: ScrapeOrchestrator = Depends(get_orchestrator),
    queue: AsyncJobQueue = Depends(get_job_queue),
    source_packs: SourcePackService = Depends(get_source_pack_service),
) -> AgentSubmitResponse:
    item = service.get_history_item(user_id=user_id, history_id=history_id)
    if not item:
        raise HTTPException(status_code=404, detail="History item not found")

    unknown = source_packs.unknown_pack_ids(item.request.source_pack_ids)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown source packs: {', '.join(unknown)}")

    if run_async:
        job_id = await queue.enqueue(item.request)
    else:
        response = await orchestrator.run_scrape_job(item.request)
        state.save_job(response)
        job_id = response.job_id

    updated = service.update_history_run(user_id=user_id, history_id=history_id, job_id=job_id, run_async=run_async)
    if not updated:
        raise HTTPException(status_code=404, detail="History item not found")
    return AgentSubmitResponse(history_id=updated.history_id, job_id=job_id, run_async=run_async)
