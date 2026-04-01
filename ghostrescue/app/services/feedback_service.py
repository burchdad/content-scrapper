from __future__ import annotations

import uuid
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import AnalystFeedback
from app.models.schemas import FeedbackIn

DECISION_TAGS = {
    "confirm_convergence": "[confirm_convergence]",
    "reject_correlation": "[reject_correlation]",
    "mark_high_priority": "[mark_high_priority]",
}

ANALYST_ROLE_MULTIPLIERS = {
    "junior_analyst": 1.0,
    "senior_analyst": 1.5,
    "trusted_operator": 2.0,
}

_DEFAULT_ANALYST_ROLE = "junior_analyst"
_ROLE_TAG_RE = re.compile(r"\[role:([a-z_]+)\]")

_DECISION_CAP = 3  # max same-type decisions per analyst per case


class DecisionCapError(ValueError):
    """Raised when the per-analyst per-decision-type cap is exceeded."""

    def __init__(self, decision_type: str, cap: int) -> None:
        super().__init__(
            f"Cap of {cap} '{decision_type}' decisions per analyst per case already reached"
        )
        self.decision_type = decision_type
        self.cap = cap


def parse_decision_type(notes: str | None) -> str | None:
    if not notes:
        return None
    lowered = notes.lower()
    for decision, tag in DECISION_TAGS.items():
        if tag in lowered:
            return decision
    return None


def compose_decision_notes(decision_type: str, notes: str | None) -> str:
    return compose_decision_notes_with_role(decision_type=decision_type, notes=notes, analyst_role=None)


def normalize_analyst_role(analyst_role: str | None) -> str:
    role = (analyst_role or "").strip().lower()
    if role in ANALYST_ROLE_MULTIPLIERS:
        return role
    return _DEFAULT_ANALYST_ROLE


def parse_decision_role(notes: str | None) -> str:
    if not notes:
        return _DEFAULT_ANALYST_ROLE
    match = _ROLE_TAG_RE.search(notes.lower())
    if not match:
        return _DEFAULT_ANALYST_ROLE
    return normalize_analyst_role(match.group(1))


def decision_weight_for_notes(notes: str | None) -> float:
    role = parse_decision_role(notes)
    return float(ANALYST_ROLE_MULTIPLIERS.get(role, 1.0))


def compose_decision_notes_with_role(decision_type: str, notes: str | None, analyst_role: str | None) -> str:
    tag = DECISION_TAGS.get(decision_type, "")
    role_tag = f"[role:{normalize_analyst_role(analyst_role)}]"
    suffix = (notes or "").strip()
    parts = [part for part in [tag, role_tag, suffix] if part]
    return " ".join(parts).strip()


class FeedbackService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, payload: FeedbackIn) -> AnalystFeedback:
        row = AnalystFeedback(
            feedback_id=f"fb-{uuid.uuid4().hex[:12]}",
            case_id=payload.case_id,
            analyst_id=payload.analyst_id,
            is_false_positive=payload.is_false_positive,
            corrected_risk_score=payload.corrected_risk_score,
            notes=payload.notes,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list(self, limit: int = 100) -> list[AnalystFeedback]:
        stmt = select(AnalystFeedback).order_by(AnalystFeedback.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def add_decision(
        self,
        *,
        case_id: str,
        analyst_id: str,
        decision_type: str,
        analyst_role: str | None = None,
        notes: str | None = None,
        corrected_risk_score: float | None = None,
    ) -> AnalystFeedback:
        tag = DECISION_TAGS.get(decision_type, "")
        if tag:
            count_stmt = (
                select(func.count())
                .select_from(AnalystFeedback)
                .where(
                    AnalystFeedback.case_id == case_id,
                    AnalystFeedback.analyst_id == analyst_id,
                    AnalystFeedback.notes.contains(tag),
                )
            )
            existing = (await self.db.scalar(count_stmt)) or 0
            if existing >= _DECISION_CAP:
                raise DecisionCapError(decision_type=decision_type, cap=_DECISION_CAP)

        is_false_positive = decision_type == "reject_correlation"
        row = AnalystFeedback(
            feedback_id=f"fb-{uuid.uuid4().hex[:12]}",
            case_id=case_id,
            analyst_id=analyst_id,
            is_false_positive=is_false_positive,
            corrected_risk_score=corrected_risk_score,
            notes=compose_decision_notes_with_role(
                decision_type=decision_type,
                notes=notes,
                analyst_role=analyst_role,
            ),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_for_case(self, case_id: str, limit: int = 200) -> list[AnalystFeedback]:
        stmt = (
            select(AnalystFeedback)
            .where(AnalystFeedback.case_id == case_id)
            .order_by(AnalystFeedback.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
