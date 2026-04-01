import httpx

from app.core.logging import get_logger
from app.models.schemas import EntityIngestPayload, IngestRequest
from app.services.ingestion.base_connector import BaseConnector

logger = get_logger(__name__)


class PublicMissingPersonsConnector(BaseConnector):
    """
    Example connector for publicly available missing persons records.

    LEGAL NOTE: This connector is a scaffold/template.
    Replace source_url_template with an actual public API endpoint
    that permits automated access (e.g. NamUs public API, NCMEC public data,
    or an NGO-provided dataset with explicit authorization).

    Do NOT point this at any private, restricted, or paid data source
    without explicit written permission.
    """

    source_name = "public_missing_persons"
    # Replace with a real public endpoint that allows automated queries
    source_url_template = "https://example.com/api/missing-persons?q={query}&limit={limit}"

    async def fetch(self, query: str, limit: int = 100) -> list[dict]:
        url = self.source_url_template.format(query=query, limit=limit)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "GhostRescue-AI/1.0 (legal-research-tool)"},
                )
                response.raise_for_status()
                return response.json().get("results", [])
        except Exception as exc:
            logger.warning("PublicMissingPersonsConnector fetch failed: %s", exc)
            return []

    def transform(self, raw_records: list[dict]) -> IngestRequest:
        entities: list[EntityIngestPayload] = []
        for record in raw_records:
            name = record.get("full_name") or record.get("name", "")
            if not name:
                continue
            aliases = [
                a for a in [record.get("alias"), record.get("nickname")] if a
            ]
            extra = {k: v for k, v in record.items() if k not in ("full_name", "name", "alias", "nickname")}
            entities.append(
                EntityIngestPayload(
                    canonical_name=name.strip(),
                    entity_type="person",
                    aliases=aliases,
                    source_name=self.source_name,
                    extra_metadata=extra,
                )
            )
        return IngestRequest(entities=entities, source_name=self.source_name)
