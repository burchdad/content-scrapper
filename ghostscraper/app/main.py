from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, RedirectResponse

from app.api.routes_agent_console import router as agent_console_router
from app.api.routes_admin import router as admin_router
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_source_packs import router as source_packs_router
from app.api.routes_safety import router as safety_router
from app.api.routes_ui import router as ui_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.discovery.search_provider import build_search_provider
from app.services.async_job_queue import AsyncJobQueue
from app.services.scrape_orchestrator import ScrapeOrchestrator
from app.services.state_service import StateService

settings = get_settings()
setup_logging(settings.log_level)

@asynccontextmanager
async def lifespan(app: FastAPI):
    state = StateService(settings.storage_root)
    orchestrator = ScrapeOrchestrator(
        storage_root=settings.storage_root,
        search_provider=build_search_provider(settings),
    )
    queue = AsyncJobQueue(orchestrator=orchestrator, state=state, maxsize=settings.async_queue_maxsize)
    await queue.start()
    app.state.job_queue = queue
    try:
        yield
    finally:
        queue = getattr(app.state, "job_queue", None)
        if queue:
            await queue.stop()


app = FastAPI(title=settings.app_name, default_response_class=ORJSONResponse, lifespan=lifespan)


@app.get("/")
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/agent", status_code=307)


app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(agent_console_router)
app.include_router(source_packs_router)
app.include_router(safety_router)
app.include_router(ui_router)
app.include_router(admin_router)
