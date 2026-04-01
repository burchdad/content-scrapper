import re

from app.models.records import ScrapedRecord


PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


def _normalize_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = PRICE_RE.search(str(value))
    if not m:
        return value
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return value


def normalize_record(record: ScrapedRecord) -> ScrapedRecord:
    cleaned = {}
    for key, value in record.data.items():
        if isinstance(value, str):
            value = value.strip() or None
        if isinstance(value, list):
            value = list(dict.fromkeys(item.strip() if isinstance(item, str) else item for item in value if item not in (None, "")))
        if "price" in key:
            value = _normalize_price(value)
        cleaned[key] = value

    images = list(dict.fromkeys(i.strip() for i in record.images if i and i.strip()))
    videos = list(dict.fromkeys(v.strip() for v in record.videos if v and v.strip()))

    return ScrapedRecord(
        source_url=record.source_url,
        canonical_url=record.canonical_url,
        record_type=record.record_type,
        title=record.title.strip() if isinstance(record.title, str) and record.title.strip() else record.title,
        data=cleaned,
        images=images,
        videos=videos,
        downloaded_images=record.downloaded_images,
        confidence=record.confidence,
        extraction_notes=record.extraction_notes,
    )


def normalize_records(records: list[ScrapedRecord]) -> list[ScrapedRecord]:
    return [normalize_record(r) for r in records]
