from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.services.semantic_service import SemanticService
from app.services.trust_service import TrustService


class CaseClusterService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.semantic = SemanticService()

    async def clusters(self) -> list[dict]:
        cfg = await TrustService(self.db).get_or_create_config()
        stmt = select(Case).order_by(Case.updated_at.desc())
        result = await self.db.execute(stmt)
        cases = result.scalars().all()

        clusters: list[list[Case]] = []
        for case in cases:
            placed = False
            for cluster in clusters:
                anchor = cluster[0]
                sim = self.semantic.similarity(case.explanation or "", anchor.explanation or "")
                if sim >= cfg.cluster_similarity_threshold:
                    cluster.append(case)
                    placed = True
                    break
            if not placed:
                clusters.append([case])

        out: list[dict] = []
        for i, group in enumerate(clusters, start=1):
            out.append(
                {
                    "cluster_id": f"cluster-{i}",
                    "size": len(group),
                    "case_ids": [c.case_id for c in group],
                    "avg_risk_score": round(sum(c.risk_score for c in group) / len(group), 2),
                }
            )
        return out
