from fastapi.testclient import TestClient

from app.api.routes_jobs import get_state_service
from app.main import app
from app.models.records import ScrapedRecord
from app.models.responses import ScrapeResponse
from app.services.state_service import StateService


def _make_record(index: int) -> ScrapedRecord:
    return ScrapedRecord(
        source_url=f"https://example.com/{index}",
        canonical_url=None,
        record_type="generic",
        title=f"Record {index}",
        data={"title": f"Record {index}", "value": index},
        images=[],
        downloaded_images=[],
        confidence=0.9,
        extraction_notes=[],
    )


def test_job_records_preview_endpoint_pages_records(tmp_path):
    state = StateService(str(tmp_path))
    job = ScrapeResponse(
        job_id="job-records-1",
        status="completed",
        plan={},
        records=[_make_record(1), _make_record(2), _make_record(3)],
        stats={"pages_processed": 1, "records_extracted": 3, "failures": 0, "elapsed_ms": 10},
        warnings=[],
    )
    state.save_job(job)

    app.dependency_overrides[get_state_service] = lambda: state
    client = TestClient(app)

    response = client.get("/api/v1/jobs/job-records-1/records", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["has_more"] is True
    assert [item["title"] for item in body["items"]] == ["Record 1", "Record 2"]

    next_page = client.get("/api/v1/jobs/job-records-1/records", params={"limit": 2, "offset": 2})
    assert next_page.status_code == 200
    next_body = next_page.json()
    assert next_body["has_more"] is False
    assert [item["title"] for item in next_body["items"]] == ["Record 3"]

    filtered = client.get(
        "/api/v1/jobs/job-records-1/records",
        params={"limit": 1, "offset": 0, "fields": "title,value,confidence"},
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["requested_fields"] == ["title", "value", "confidence"]
    assert filtered_body["items"][0]["title"] == "Record 1"
    assert filtered_body["items"][0]["data"] == {"value": 1}
    assert filtered_body["items"][0]["confidence"] == 0.9
    assert filtered_body["items"][0]["images"] == []

    missing = client.get("/api/v1/jobs/missing-job/records")
    assert missing.status_code == 404

    app.dependency_overrides.clear()
