from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.case import Case
from app.models.entity_event import EntityEvent


class AnalystSummaryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_case_summary(self, case: Case) -> dict:
        entity_id = case.entity_ids[0] if case.entity_ids else None
        events: list[EntityEvent] = []
        if entity_id:
            ev_stmt = (
                select(EntityEvent)
                .where(EntityEvent.entity_id == entity_id)
                .order_by(EntityEvent.event_timestamp.desc())
                .limit(20)
            )
            ev_res = await self.db.execute(ev_stmt)
            events = ev_res.scalars().all()

        al_stmt = select(Alert).where(Alert.case_id == case.case_id).order_by(Alert.triggered_at.desc())
        al_res = await self.db.execute(al_stmt)
        alerts = al_res.scalars().all()

        now = datetime.now(UTC)
        seven_days = now - timedelta(days=7)
        recent_events = [
            e
            for e in events
            if (e.event_timestamp if e.event_timestamp.tzinfo else e.event_timestamp.replace(tzinfo=UTC)) >= seven_days
        ]
        source_count = len({e.source_name for e in events if e.source_name})

        narrative = (
            f"Case {case.case_id} remains {case.status}. "
            f"Current risk score is {case.risk_score:.1f}/100 with confidence {case.confidence_score:.2f}. "
            f"Signals observed: {', '.join(case.signal_ids) if case.signal_ids else 'none recorded'}. "
            f"Entity activity includes {len(events)} timeline events across {source_count} sources, "
            f"with {len(recent_events)} events in the last 7 days. "
            f"Active alerts: {sum(1 for a in alerts if not a.acknowledged)}. "
            "This summary reflects automated triage indicators and requires human analyst validation."
        )

        return {
            "case_id": case.case_id,
            "status": case.status,
            "risk_score": case.risk_score,
            "confidence_score": case.confidence_score,
            "system_confidence": case.system_confidence,
            "narrative": narrative,
            "event_count": len(events),
            "recent_event_count_7d": len(recent_events),
            "source_count": source_count,
            "alert_count": len(alerts),
            "unacknowledged_alert_count": sum(1 for a in alerts if not a.acknowledged),
        }
