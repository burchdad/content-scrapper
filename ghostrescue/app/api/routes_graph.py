from fastapi import APIRouter, HTTPException

from app.core.graph_db import get_driver
from app.models.schemas import GraphAnalyticsResponse, GraphResponse
from app.services.graph.graph_service import GraphService

router = APIRouter(prefix="/api/v1", tags=["graph"])


@router.get("/graph/{entity_id}", response_model=GraphResponse)
async def get_entity_graph(entity_id: str) -> GraphResponse:
    """
    Retrieve the knowledge graph neighborhood for an entity (up to depth 2).

    Returns nodes (Entity, Signal, Location, Event) and their relationships.
    Falls back gracefully with an empty graph if Neo4j is unavailable.
    """
    try:
        driver = get_driver()
        service = GraphService(driver)
        return await service.get_entity_graph(entity_id=entity_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Graph service unavailable: {exc}",
        ) from exc


@router.get("/graph/{entity_id}/analytics", response_model=GraphAnalyticsResponse)
async def get_entity_graph_analytics(entity_id: str) -> GraphAnalyticsResponse:
    try:
        driver = get_driver()
        service = GraphService(driver)
        graph = await service.get_entity_graph(entity_id=entity_id)
        return service.analytics(graph)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Graph analytics unavailable: {exc}",
        ) from exc
