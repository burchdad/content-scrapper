"""Cross-source AI enrichment for ingested signals.

This service is designed to run *after* deterministic ingestion for any source.
It enriches recent signals with:
- concise AI summary
- indicator tags
- optional confidence adjustment

It never raises hard failures to callers; enrichment is best-effort.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal import Signal
from app.services.legal_ai_enrichment import LegalAIEnricher


def _matches_source(source_name: str | None, patterns: list[str]) -> bool:
    if not source_name:
        return False

    value = source_name.strip().lower()
    for pattern in patterns:
        p = pattern.strip().lower()
        if not p:
            continue
        if p.endswith("*"):
            if value.startswith(p[:-1]):
                return True
        elif value == p:
            return True
    return False


def _already_enriched(meta: dict[str, Any]) -> bool:
    ai = meta.get("ai")
    return isinstance(ai, dict) and bool(ai.get("summary"))


class AISignalEnrichmentService:
    """Apply optional LLM enrichment to recent signals for selected sources."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ):
        self.session = session
        self.enricher = LegalAIEnricher(
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
        )

    @property
    def enabled(self) -> bool:
        return self.enricher.enabled

    async def enrich_recent_signals(
        self,
        *,
        source_patterns: list[str],
        max_records: int = 20,
    ) -> dict[str, Any]:
        """Enrich recent signals matching ``source_patterns``.

        ``source_patterns`` supports exact match (e.g. ``interpol``)
        and prefix match using ``*`` (e.g. ``newsapi-*``).
        """
        if max_records <= 0:
            return {
                "enabled": self.enabled,
                "provider": self.enricher.provider,
                "targeted": 0,
                "enriched": 0,
            }

        # Pull a larger window and filter in-memory for portability.
        window = max_records * 8
        result = await self.session.execute(
            select(Signal).order_by(desc(Signal.detected_at)).limit(window)
        )
        recent = list(result.scalars().all())

        targeted = 0
        enriched = 0

        for signal in recent:
            if enriched >= max_records:
                break
            if not _matches_source(signal.source_name, source_patterns):
                continue

            targeted += 1
            meta = signal.extra_metadata or {}
            if _already_enriched(meta):
                continue

            snippet = (signal.raw_text_snippet or signal.evidence or "").strip()
            if not snippet:
                continue

            try:
                ai = await self.enricher.enrich(
                    case_name=(signal.label or "Legal Signal").strip(),
                    court_name=str(meta.get("court_name") or signal.source_name or "Unknown Source"),
                    query=str(meta.get("query") or signal.signal_type or "signal classification"),
                    snippet=snippet[:1200],
                    docket_number=str(meta.get("docket_number") or ""),
                    date_filed=str(meta.get("date_filed") or ""),
                )
            except Exception:
                continue

            if not ai:
                continue

            ai_summary = str(ai.get("summary") or "").strip()
            ai_conf = ai.get("confidence")

            updated_meta = dict(meta)
            updated_meta["ai"] = ai
            if ai_summary:
                updated_meta["ai_summary"] = ai_summary
            signal.extra_metadata = updated_meta

            if ai_summary and "AI Summary:" not in (signal.evidence or ""):
                signal.evidence = f"{(signal.evidence or '').strip()} | AI Summary: {ai_summary}"[:2000]

            if isinstance(ai_conf, (int, float)):
                # Smooth confidence update to preserve deterministic baseline.
                signal.confidence = max(0.0, min(1.0, (signal.confidence * 0.7) + (float(ai_conf) * 0.3)))

            enriched += 1

        return {
            "enabled": self.enabled,
            "provider": self.enricher.provider,
            "targeted": targeted,
            "enriched": enriched,
        }
