from app.models.records import ScrapedRecord


class ConfidenceScorer:
    def score(self, record: ScrapedRecord, required_fields: list[str], requested_images: bool = False) -> float:
        score = 0.50

        if record.data.get("json_ld"):
            score += 0.20
        if record.canonical_url:
            score += 0.10

        populated = sum(1 for f in required_fields if record.data.get(f) not in (None, "", [], {}))
        if required_fields and populated / len(required_fields) >= 0.6:
            score += 0.10

        if record.title and record.data.get("title") and record.title.lower() in str(record.data.get("title")).lower():
            score += 0.05

        if requested_images and record.images:
            score += 0.05

        if len(record.data) <= 1:
            score -= 0.10
        if not record.title:
            score -= 0.10

        return max(0.0, min(1.0, round(score, 3)))
