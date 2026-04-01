from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/ping")
async def ping() -> dict:
    return {"pong": True}
