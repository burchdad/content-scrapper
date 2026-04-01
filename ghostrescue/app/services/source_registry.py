"""Source Registry — the gatekeeper between data acquisition and intelligence scoring.

Every source that touches GhostRescue must appear here.  The registry defines:
  - Whether the source is approved for direct ingest
  - Its trust_level (used by scoring to cap influence)
  - Its max_influence cap (0.0 – 1.0, multiplied against the raw signal weight)
  - Whether the source requires staging (human review before it enters scoring)

Trust Levels (highest → lowest)
---------------------------------
law_enforcement_direct   FBI Most Wanted, Interpol Red Notices
validated_public         NCMEC, NamUs, CourtListener — authoritative public registries
validated_osint          GDELT, Polaris, NewsAPI — quality-filtered OSINT feeds
unvalidated_osint        Anything submitted via the scraper staging path, not yet reviewed
staged_pending           Present in staging queue, awaiting analyst approval

Design rule
-----------
GhostScraper NEVER writes directly into GhostRescue ingest endpoints.
It submits to POST /api/v1/staging/submit.  A human (or auto-validator) must
promote the source to validated_osint or better before it influences scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Trust level constants
# ---------------------------------------------------------------------------

TRUST_LAW_ENFORCEMENT = "law_enforcement_direct"
TRUST_VALIDATED_PUBLIC = "validated_public"
TRUST_VALIDATED_OSINT  = "validated_osint"
TRUST_UNVALIDATED      = "unvalidated_osint"
TRUST_STAGED_PENDING   = "staged_pending"

# Ordered from most to least authoritative
TRUST_LEVEL_ORDER = [
    TRUST_LAW_ENFORCEMENT,
    TRUST_VALIDATED_PUBLIC,
    TRUST_VALIDATED_OSINT,
    TRUST_UNVALIDATED,
    TRUST_STAGED_PENDING,
]

# Influence cap per trust level  (signal weight will be multiplied by this)
TRUST_LEVEL_INFLUENCE_CAP: dict[str, float] = {
    TRUST_LAW_ENFORCEMENT: 1.0,    # full weight
    TRUST_VALIDATED_PUBLIC: 0.85,  # slight discount — still official
    TRUST_VALIDATED_OSINT:  0.60,  # corroborating only
    TRUST_UNVALIDATED:      0.20,  # near-zero until reviewed
    TRUST_STAGED_PENDING:   0.0,   # zero influence until promoted
}


# ---------------------------------------------------------------------------
# Source entry definition
# ---------------------------------------------------------------------------

@dataclass
class SourceEntry:
    source_key: str               # canonical key used in source_name fields
    display_name: str
    trust_level: str
    direct_ingest: bool           # True = allowed into /api/v1/ingest directly
    requires_staging: bool        # True = must pass through staging before scoring
    notes: str = ""
    approved_endpoints: list[str] = field(default_factory=list)  # ingest routes this source may use


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: list[SourceEntry] = [
    # ---- Law Enforcement ----
    SourceEntry(
        source_key="fbi",
        display_name="FBI Most Wanted",
        trust_level=TRUST_LAW_ENFORCEMENT,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/fbi"],
    ),
    SourceEntry(
        source_key="fbi_wanted",
        display_name="FBI Wanted (alt key)",
        trust_level=TRUST_LAW_ENFORCEMENT,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/fbi"],
    ),
    SourceEntry(
        source_key="interpol",
        display_name="Interpol Red Notices",
        trust_level=TRUST_LAW_ENFORCEMENT,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/interpol"],
    ),
    # ---- Validated Public Registries ----
    SourceEntry(
        source_key="ncmec",
        display_name="NCMEC Missing Kids",
        trust_level=TRUST_VALIDATED_PUBLIC,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/ncmec"],
    ),
    SourceEntry(
        source_key="namus",
        display_name="NamUs Missing Persons",
        trust_level=TRUST_VALIDATED_PUBLIC,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/namus"],
    ),
    SourceEntry(
        source_key="courtlistener",
        display_name="CourtListener Legal Records",
        trust_level=TRUST_VALIDATED_PUBLIC,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/courtlistener"],
    ),
    # ---- Validated OSINT ----
    SourceEntry(
        source_key="gdelt",
        display_name="GDELT Global Event Database",
        trust_level=TRUST_VALIDATED_OSINT,
        direct_ingest=True,
        requires_staging=False,
        notes="No API key required. Bounded by max_records_per_query.",
        approved_endpoints=["/api/v1/ingest/gdelt"],
    ),
    SourceEntry(
        source_key="newsapi",
        display_name="NewsAPI.org",
        trust_level=TRUST_VALIDATED_OSINT,
        direct_ingest=True,
        requires_staging=False,
        notes="Requires NEWSAPI_KEY in settings.",
        approved_endpoints=["/api/v1/ingest/newsapi"],
    ),
    SourceEntry(
        source_key="polaris",
        display_name="Polaris Project",
        trust_level=TRUST_VALIDATED_OSINT,
        direct_ingest=True,
        requires_staging=False,
        notes="File-mode safe; live mode may 403. See polaris ingester.",
        approved_endpoints=["/api/v1/ingest/polaris"],
    ),
    SourceEntry(
        source_key="polaris_project",
        display_name="Polaris Project (alt key)",
        trust_level=TRUST_VALIDATED_OSINT,
        direct_ingest=True,
        requires_staging=False,
        approved_endpoints=["/api/v1/ingest/polaris"],
    ),
    # ---- Unvalidated / Staged (GhostScraper output lands here) ----
    SourceEntry(
        source_key="ghostscraper",
        display_name="GhostScraper Discovery Engine",
        trust_level=TRUST_UNVALIDATED,
        direct_ingest=False,
        requires_staging=True,
        notes="All GhostScraper findings must pass staging before scoring.",
        approved_endpoints=["/api/v1/staging/submit"],
    ),
    SourceEntry(
        source_key="scraper_unvalidated",
        display_name="Unvalidated Scraper Source",
        trust_level=TRUST_UNVALIDATED,
        direct_ingest=False,
        requires_staging=True,
        approved_endpoints=["/api/v1/staging/submit"],
    ),
]

# Build lookup indices
_by_key: dict[str, SourceEntry] = {}
for _entry in _REGISTRY:
    _by_key[_entry.source_key.lower()] = _entry


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_source_entry(source_name: str) -> SourceEntry | None:
    """Return the registry entry for a source name (prefix-match friendly)."""
    name = source_name.lower().strip()
    if name in _by_key:
        return _by_key[name]
    # prefix scan (e.g., "fbi-most-wanted" → "fbi")
    for key, entry in _by_key.items():
        if name.startswith(key):
            return entry
    return None


def is_source_approved(source_name: str) -> bool:
    """Return True if this source is allowed to ingest directly into GhostRescue."""
    entry = get_source_entry(source_name)
    return entry is not None and entry.direct_ingest


def requires_staging(source_name: str) -> bool:
    """Return True if this source must pass staging before scoring."""
    entry = get_source_entry(source_name)
    if entry is None:
        return True  # unknown sources always require staging
    return entry.requires_staging


def get_trust_level(source_name: str) -> str:
    """Return the trust_level string for a source (default: unvalidated_osint)."""
    entry = get_source_entry(source_name)
    return entry.trust_level if entry else TRUST_UNVALIDATED


def get_influence_cap(source_name: str) -> float:
    """Return the 0.0–1.0 influence multiplier for this source."""
    trust = get_trust_level(source_name)
    return TRUST_LEVEL_INFLUENCE_CAP.get(trust, 0.20)


def list_approved_sources() -> list[dict]:
    """Return all approved sources for the /api/v1/staging/sources endpoint."""
    return [
        {
            "source_key": e.source_key,
            "display_name": e.display_name,
            "trust_level": e.trust_level,
            "direct_ingest": e.direct_ingest,
            "requires_staging": e.requires_staging,
            "influence_cap": TRUST_LEVEL_INFLUENCE_CAP.get(e.trust_level, 0.20),
            "notes": e.notes,
        }
        for e in _REGISTRY
    ]


def add_source(entry: SourceEntry) -> None:
    """Dynamically register a new source (e.g., approved through staging)."""
    _by_key[entry.source_key.lower()] = entry
    _REGISTRY.append(entry)
