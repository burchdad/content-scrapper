from pathlib import Path

import httpx

from app.models.records import ScrapedRecord


async def download_record_images(records: list[ScrapedRecord], job_id: str, storage_root: str) -> list[ScrapedRecord]:
    out_dir = Path(storage_root) / "images" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=15.0) as client:
        for idx, record in enumerate(records):
            downloaded = []
            for i, image_url in enumerate(record.images):
                try:
                    resp = await client.get(image_url)
                    if resp.status_code >= 400:
                        continue
                    suffix = ".jpg"
                    ctype = resp.headers.get("content-type", "")
                    if "png" in ctype:
                        suffix = ".png"
                    elif "webp" in ctype:
                        suffix = ".webp"
                    path = out_dir / f"r{idx}_img{i}{suffix}"
                    path.write_bytes(resp.content)
                    downloaded.append(str(path))
                except Exception:
                    continue
            record.downloaded_images = downloaded

    return records
