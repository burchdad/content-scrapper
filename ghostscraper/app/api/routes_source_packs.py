from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.source_packs import SourcePack
from app.services.source_pack_service import SourcePackService

router = APIRouter(prefix="/api/v1/source-packs", tags=["source-packs"])


def get_source_pack_service() -> SourcePackService:
    return SourcePackService()


@router.get("", response_model=list[SourcePack])
async def list_source_packs(
    category: str | None = Query(default=None),
    service: SourcePackService = Depends(get_source_pack_service),
) -> list[SourcePack]:
    return service.list_packs(category=category)


@router.get("/{pack_id}", response_model=SourcePack)
async def get_source_pack(
    pack_id: str,
    service: SourcePackService = Depends(get_source_pack_service),
) -> SourcePack:
    pack = service.get_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Source pack not found")
    return pack