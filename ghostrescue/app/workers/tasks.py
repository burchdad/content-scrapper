import asyncio

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="ingest_entity_batch", bind=True, max_retries=3)
def ingest_entity_batch(self, entity_payloads: list[dict], source_name: str = "unknown") -> dict:
    """
    Celery task for async batch entity ingestion.

    Runs the full entity resolution pipeline for each payload dict.
    Retries up to 3 times on transient DB failures.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.schemas import EntityIngestPayload
    from app.services.entity_resolution.resolver import EntityResolver

    async def _run() -> dict:
        results = []
        errors = []
        async with AsyncSessionLocal() as db:
            resolver = EntityResolver(db)
            for payload_dict in entity_payloads:
                try:
                    payload = EntityIngestPayload(**payload_dict)
                    if payload.source_name == "unknown":
                        payload.source_name = source_name
                    result = await resolver.resolve(payload)
                    results.append(
                        {
                            "entity_id": result.entity_id,
                            "action": result.action,
                            "match_score": result.match_score,
                        }
                    )
                except Exception as exc:
                    logger.warning("Failed to resolve entity %s: %s", payload_dict.get("canonical_name"), exc)
                    errors.append({"payload": payload_dict, "error": str(exc)})
        return {"processed": len(results), "errors": len(errors), "results": results}

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("ingest_entity_batch task failed: %s", exc)
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="analyze_text_batch")
def analyze_text_batch(texts: list[str], entity_id: str | None = None) -> dict:
    """
    Celery task: run NLP + risk scoring on a batch of text snippets.
    Stores results for later review — does not auto-escalate.
    """
    from app.services.nlp.classifier import NLPClassifier
    from app.services.scoring.risk_scorer import RiskScorer

    classifier = NLPClassifier()
    scorer = RiskScorer()
    results = []

    for text in texts:
        signals = classifier.classify(text)
        score = scorer.score(signals)
        results.append(
            {
                "entity_id": entity_id,
                "risk_score": score.risk_score,
                "risk_band": score.risk_band,
                "signal_count": len(signals),
                "explanation": score.explanation,
            }
        )

    return {"analyzed": len(results), "results": results}
