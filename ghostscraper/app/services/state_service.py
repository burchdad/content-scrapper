import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.records import ScrapedRecord
from app.models.responses import ScrapeResponse


class StateService:
    def __init__(self, root: str) -> None:
        self.jobs_dir = Path(root) / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def save_job(self, response: ScrapeResponse) -> None:
        path = self.jobs_dir / f"{response.job_id}.json"
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    def create_status_job(self, job_id: str | None, status: str) -> str:
        from app.services.job_service import create_job_id

        new_job_id = job_id or create_job_id()
        placeholder = ScrapeResponse(
            job_id=new_job_id,
            status=status,
            plan={},
            records=[],
            stats={"pages_processed": 0, "records_extracted": 0, "failures": 0, "elapsed_ms": 0},
            warnings=[],
            diagnostics=None,
        )
        self.save_job(placeholder)
        return new_job_id

    def get_job(self, job_id: str) -> ScrapeResponse | None:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        return ScrapeResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def get_job_records_page(
        self,
        job_id: str,
        limit: int = 20,
        offset: int = 0,
        fields: list[str] | None = None,
    ) -> tuple[ScrapeResponse | None, list[ScrapedRecord], int, bool]:
        response = self.get_job(job_id)
        if not response:
            return None, [], 0, False

        total = len(response.records)
        items = response.records[offset : offset + limit]
        if fields:
            items = [self._filter_record(record, fields) for record in items]
        has_more = offset + limit < total
        return response, items, total, has_more

    def get_all_job_records(self, job_id: str, fields: list[str] | None = None) -> tuple[ScrapeResponse | None, list[ScrapedRecord]]:
        response = self.get_job(job_id)
        if not response:
            return None, []

        items = response.records
        if fields:
            items = [self._filter_record(record, fields) for record in items]
        return response, items

    @staticmethod
    def _filter_record(record: ScrapedRecord, fields: list[str]) -> ScrapedRecord:
        requested = {field.strip() for field in fields if field.strip()}
        top_level_fields = {
            "source_url",
            "canonical_url",
            "record_type",
            "title",
            "images",
            "videos",
            "downloaded_images",
            "confidence",
            "extraction_notes",
        }
        top_level = {
            "source_url": record.source_url,
            "canonical_url": record.canonical_url,
            "record_type": record.record_type,
            "title": record.title,
            "images": record.images,
            "videos": record.videos,
            "downloaded_images": record.downloaded_images,
            "confidence": record.confidence,
            "extraction_notes": record.extraction_notes,
        }
        filtered_data = {
            key: value for key, value in record.data.items() if key in requested and key not in top_level_fields
        }

        return ScrapedRecord(
            source_url=record.source_url,
            canonical_url=top_level["canonical_url"] if "canonical_url" in requested else None,
            record_type=record.record_type,
            title=top_level["title"] if "title" in requested else None,
            data=filtered_data,
            images=top_level["images"] if "images" in requested else [],
            videos=top_level["videos"] if "videos" in requested else [],
            downloaded_images=top_level["downloaded_images"] if "downloaded_images" in requested else [],
            confidence=top_level["confidence"] if "confidence" in requested else None,
            extraction_notes=top_level["extraction_notes"] if "extraction_notes" in requested else [],
        )

    def list_jobs_page(
        self,
        limit: int = 20,
        status: str | None = None,
        cursor: str | None = None,
    ) -> tuple[list[tuple[ScrapeResponse, str]], str | None]:
        files = sorted(
            self.jobs_dir.glob("*.json"),
            key=lambda p: (p.stat().st_mtime_ns, p.stem),
            reverse=True,
        )

        cursor_key: tuple[int, str] | None = None
        if cursor:
            cursor_key = self._decode_cursor(cursor)

        results: list[tuple[ScrapeResponse, str]] = []
        has_more = False
        next_cursor: str | None = None

        for path in files:
            file_key = (path.stat().st_mtime_ns, path.stem)
            if cursor_key and not (file_key < cursor_key):
                continue

            payload = json.loads(path.read_text(encoding="utf-8"))
            response = ScrapeResponse.model_validate(payload)
            if status and response.status != status:
                continue

            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            results.append((response, updated_at))
            if len(results) == limit:
                next_cursor = self._encode_cursor(file_key)
                continue
            if len(results) > limit:
                has_more = True
                break

        trimmed = results[:limit]
        if not has_more:
            next_cursor = None
        return trimmed, next_cursor

    @staticmethod
    def _encode_cursor(key: tuple[int, str]) -> str:
        raw = json.dumps({"mtime_ns": key[0], "job_id": key[1]}, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[int, str]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            payload = json.loads(decoded)
            mtime_ns = int(payload["mtime_ns"])
            job_id = str(payload["job_id"])
            return (mtime_ns, job_id)
        except Exception as exc:
            raise ValueError("Invalid cursor") from exc
