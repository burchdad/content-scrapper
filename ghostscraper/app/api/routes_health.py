from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("")
async def health() -> dict:
    return {"status": "ok", "service": "GhostScraper"}


@router.get("/dependencies")
async def dependencies() -> dict:
    settings = get_settings()
    checks = {
        "storage_access": Path(settings.storage_root).exists(),
    }
    try:
        from playwright.async_api import async_playwright  # noqa: F401

        checks["playwright_import"] = True
    except Exception:
        checks["playwright_import"] = False

    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}
