from abc import ABC, abstractmethod

from app.models.schemas import IngestRequest


class BaseConnector(ABC):
    """
    Abstract base for all data ingestion connectors.

    LEGAL CONSTRAINT: Every connector implementation MUST only access
    publicly available, legally permitted data sources. Any connector
    attempting to access non-public, unauthorized, or illegal sources
    must not be implemented or deployed.
    """

    source_name: str = "unknown"

    @abstractmethod
    async def fetch(self, query: str, limit: int = 100) -> list[dict]:
        """Fetch raw records from the permitted public source."""

    @abstractmethod
    def transform(self, raw_records: list[dict]) -> IngestRequest:
        """Transform raw records into a structured IngestRequest."""

    async def run(self, query: str, limit: int = 100) -> IngestRequest:
        raw = await self.fetch(query=query, limit=limit)
        return self.transform(raw)
