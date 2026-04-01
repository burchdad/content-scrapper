class GhostScraperError(Exception):
    """Base project exception."""


class FetchError(GhostScraperError):
    """Raised when a fetch operation fails."""
