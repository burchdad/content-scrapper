from io import StringIO
from pathlib import Path

import pandas as pd

from app.models.records import ScrapedRecord


def export_json(records: list[ScrapedRecord], path: Path) -> None:
    path.write_text(
        "[\n" + ",\n".join(r.model_dump_json(indent=2) for r in records) + "\n]",
        encoding="utf-8",
    )


def export_csv(records: list[ScrapedRecord], path: Path) -> None:
    path.write_text(render_csv(records), encoding="utf-8")


def render_csv(records: list[ScrapedRecord]) -> str:
    rows: list[dict] = []
    for record in records:
        row = {
            "source_url": record.source_url,
            "canonical_url": record.canonical_url,
            "record_type": record.record_type,
            "title": record.title,
            "images": "|".join(record.images),
            "videos": "|".join(record.videos),
            "confidence": record.confidence,
        }
        for k, v in record.data.items():
            row[k] = v
        rows.append(row)

    buffer = StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    return buffer.getvalue()
