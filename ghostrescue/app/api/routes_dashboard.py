"""Dashboard routes for GhostRescue UI."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the main dashboard page."""
    dashboard_path = Path(__file__).parent.parent / "static" / "dashboard.html"
    try:
        with open(dashboard_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1>",
            status_code=404
        )


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard_alt():
    """Alternative dashboard route."""
    return await serve_dashboard()
