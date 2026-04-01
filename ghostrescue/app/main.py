from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_alerts import router as alerts_router
from app.api.routes_analyze import router as analyze_router
from app.api.routes_cases import router as cases_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_entities import router as entities_router
from app.api.routes_explainability import router as explainability_router
from app.api.routes_graph import router as graph_router
from app.api.routes_health import router as health_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_staging import router as staging_router
from app.api.routes_trust import router as trust_router
from app.api.routes_links import router as links_router
from app.api.routes_system import router as system_router
from app.core.config import get_settings
from app.core.database import create_tables
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(debug=settings.debug)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    await create_tables()
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "A legal, compliant intelligence platform for identifying human trafficking "
        "and missing persons patterns from **public, permitted data sources only**.\n\n"
        f"⚠️ **Disclaimer:** {settings.disclaimer}"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(staging_router)
app.include_router(entities_router)
app.include_router(analyze_router)
app.include_router(graph_router)
app.include_router(alerts_router)
app.include_router(cases_router)
app.include_router(trust_router)
app.include_router(explainability_router)
app.include_router(dashboard_router)
app.include_router(links_router)
app.include_router(system_router)

# Mount static files (CSS, JS, etc.)
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
