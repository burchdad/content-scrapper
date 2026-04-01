import time

from fastapi.testclient import TestClient

from app.api.routes_jobs import get_state_service
from app.main import app
from app.models.responses import ScrapeResponse
from app.services.state_service import StateService


def _build_response(job_id: str, status: str, records_extracted: int) -> ScrapeResponse:
    return ScrapeResponse(
        job_id=job_id,
        status=status,
        plan={},
        records=[],
        stats={
            "pages_processed": records_extracted,
            "records_extracted": records_extracted,
            "failures": 0,
            "elapsed_ms": records_extracted * 10,
        },
        warnings=[],
    )


def test_list_jobs_returns_most_recent_first_with_filter(tmp_path):
    state = StateService(str(tmp_path))
    state.save_job(_build_response("job-old", "completed", 1))
    time.sleep(0.01)
    state.save_job(_build_response("job-mid", "failed", 0))
    time.sleep(0.01)
    state.save_job(_build_response("job-new", "queued", 0))

    app.dependency_overrides[get_state_service] = lambda: state
    client = TestClient(app)

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.json()
    assert [item["job_id"] for item in body["items"][:3]] == ["job-new", "job-mid", "job-old"]
    assert body["next_cursor"] is None

    filtered = client.get("/api/v1/jobs", params={"status": "failed"})
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert len(filtered_body["items"]) == 1
    assert filtered_body["items"][0]["job_id"] == "job-mid"
    assert filtered_body["items"][0]["status"] == "failed"

    paged = client.get("/api/v1/jobs", params={"limit": 2})
    assert paged.status_code == 200
    paged_body = paged.json()
    assert [item["job_id"] for item in paged_body["items"]] == ["job-new", "job-mid"]
    assert isinstance(paged_body["next_cursor"], str)

    next_page = client.get("/api/v1/jobs", params={"limit": 2, "cursor": paged_body["next_cursor"]})
    assert next_page.status_code == 200
    next_page_body = next_page.json()
    assert [item["job_id"] for item in next_page_body["items"]] == ["job-old"]
    assert next_page_body["next_cursor"] is None

    bad_cursor = client.get("/api/v1/jobs", params={"cursor": "not-base64"})
    assert bad_cursor.status_code == 400

    app.dependency_overrides.clear()
