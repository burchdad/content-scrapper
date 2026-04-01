import hashlib
import json

from app.models.records import ScrapedRecord


class Deduper:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def _key(self, record: ScrapedRecord) -> str:
        core = {
            "canonical": record.canonical_url or "",
            "source": record.source_url,
            "type": record.record_type,
            "title": record.title or "",
            "data": record.data,
        }
        raw = json.dumps(core, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def filter_new_records(self, records: list[ScrapedRecord]) -> list[ScrapedRecord]:
        out: list[ScrapedRecord] = []
        for record in records:
            key = self._key(record)
            if key in self.seen:
                continue
            self.seen.add(key)
            out.append(record)
        return out
