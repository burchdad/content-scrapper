from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import AnalystFeedback
from app.models.trust import TrustConfig


class TrustService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create_config(self) -> TrustConfig:
        stmt = select(TrustConfig).where(TrustConfig.config_key == "default")
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()
        if config:
            return config

        config = TrustConfig(config_key="default")
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def update_config(
        self,
        risk_medium_threshold: float | None = None,
        risk_high_threshold: float | None = None,
        risk_critical_threshold: float | None = None,
        cluster_similarity_threshold: float | None = None,
        false_positive_penalty: float | None = None,
    ) -> TrustConfig:
        config = await self.get_or_create_config()
        if risk_medium_threshold is not None:
            config.risk_medium_threshold = risk_medium_threshold
        if risk_high_threshold is not None:
            config.risk_high_threshold = risk_high_threshold
        if risk_critical_threshold is not None:
            config.risk_critical_threshold = risk_critical_threshold
        if cluster_similarity_threshold is not None:
            config.cluster_similarity_threshold = cluster_similarity_threshold
        if false_positive_penalty is not None:
            config.false_positive_penalty = false_positive_penalty
        config.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def false_positive_rate(self) -> float:
        total_stmt = select(AnalystFeedback)
        result = await self.db.execute(total_stmt)
        rows = result.scalars().all()
        if not rows:
            return 0.0
        fp = sum(1 for r in rows if r.is_false_positive)
        return round(fp / len(rows), 3)

    async def adaptive_penalty(self) -> float:
        cfg = await self.get_or_create_config()
        fp_rate = await self.false_positive_rate()
        return round(min(0.35, cfg.false_positive_penalty + (fp_rate * 0.25)), 3)
