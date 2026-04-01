"""Base ingester class for all data sources."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class BaseIngester(ABC):
    """Abstract base class for all data source ingesters."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.imported_count = 0
        self.error_count = 0
        self.start_time: datetime | None = None

    @abstractmethod
    async def ingest(self) -> dict[str, Any]:
        """
        Ingest data from the source.
        
        Returns:
            dict with keys: imported_count, error_count, duration_seconds, details
        """
        pass

    def report(self) -> dict[str, Any]:
        """Generate ingestion report."""
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        return {
            "imported_count": self.imported_count,
            "error_count": self.error_count,
            "duration_seconds": round(duration, 2),
        }
