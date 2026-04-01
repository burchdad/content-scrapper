from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.alert import Alert
from app.models.schemas import AlertListResponse, AlertOut

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    acknowledged: bool | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """List alerts with optional filters for acknowledgement status and severity."""
    stmt = select(Alert).order_by(Alert.triggered_at.desc()).limit(limit)
    count_stmt = select(func.count()).select_from(Alert)
    unack_stmt = select(func.count()).select_from(Alert).where(Alert.acknowledged == False)  # noqa: E712

    if acknowledged is not None:
        stmt = stmt.where(Alert.acknowledged == acknowledged)
        count_stmt = count_stmt.where(Alert.acknowledged == acknowledged)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
        count_stmt = count_stmt.where(Alert.severity == severity)

    result = await db.execute(stmt)
    total_result = await db.execute(count_stmt)
    unack_result = await db.execute(unack_stmt)

    alerts = result.scalars().all()
    total = total_result.scalar_one()
    unacknowledged_count = unack_result.scalar_one()

    return AlertListResponse(
        alerts=[_alert_out(a) for a in alerts],
        total=total,
        unacknowledged_count=unacknowledged_count,
    )


@router.patch("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: str,
    acknowledged_by: str = Query(default="analyst"),
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    """Mark an alert as acknowledged."""
    stmt = select(Alert).where(Alert.alert_id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(UTC)
    alert.acknowledged_by = acknowledged_by
    await db.commit()
    await db.refresh(alert)
    return _alert_out(alert)


def _alert_out(alert: Alert) -> AlertOut:
    return AlertOut(
        alert_id=alert.alert_id,
        case_id=alert.case_id,
        severity=alert.severity,
        message=alert.message,
        triggered_at=alert.triggered_at,
        acknowledged=alert.acknowledged,
        acknowledged_at=alert.acknowledged_at,
    )
