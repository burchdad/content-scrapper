from fastapi.testclient import TestClient

from app.api.routes_jobs import get_state_service
from app.main import app
from app.models.records import ScrapedRecord
from app.models.responses import JobDiagnostics, JobWarning, ScrapeResponse
from app.services.state_service import StateService


def test_job_summary_endpoint_completed_with_diagnostics(tmp_path):
    state = StateService(str(tmp_path))
    job = ScrapeResponse(
        job_id="job-summary-1",
        status="completed",
        plan={"intent": "media", "strategy": "search_then_scrape"},
        records=[
            ScrapedRecord(
                source_url="https://example.com/a",
                canonical_url=None,
                record_type="media",
                title="Example A",
                data={},
                images=[],
                videos=[],
                downloaded_images=[],
                confidence=0.8,
                extraction_notes=[],
            )
        ],
        stats={"pages_processed": 2, "records_extracted": 1, "failures": 0, "elapsed_ms": 250},
        warnings=[JobWarning(code="SOURCE_PACK_AUGMENTED", message="augmented")],
        diagnostics=JobDiagnostics(
            primary_issue=None,
            recommendation="Run complete. Use records preview or CSV export for structured review.",
            warning_counts={"SOURCE_PACK_AUGMENTED": 1},
        ),
    )
    state.save_job(job)

    app.dependency_overrides[get_state_service] = lambda: state
    client = TestClient(app)

    response = client.get("/api/v1/jobs/job-summary-1/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-summary-1"
    assert body["status"] == "completed"
    assert body["headline"] == "Extracted 1 records from 2 pages."
    assert body["recommendation"]
    assert body["warning_counts"] == {"SOURCE_PACK_AUGMENTED": 1}
    assert body["sample_source_urls"] == ["https://example.com/a"]

    app.dependency_overrides.clear()


def test_job_summary_endpoint_queued_job(tmp_path):
    state = StateService(str(tmp_path))
    job = ScrapeResponse(
        job_id="job-summary-queued",
        status="queued",
        plan={},
        records=[],
        stats={"pages_processed": 0, "records_extracted": 0, "failures": 0, "elapsed_ms": 0},
        warnings=[],
        diagnostics=None,
    )
    state.save_job(job)

    app.dependency_overrides[get_state_service] = lambda: state
    client = TestClient(app)

    response = client.get("/api/v1/jobs/job-summary-queued/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "Job is queued. Processing has not finished yet."
    assert body["records_extracted"] == 0

    missing = client.get("/api/v1/jobs/missing-job/summary")
    assert missing.status_code == 404

    app.dependency_overrides.clear()