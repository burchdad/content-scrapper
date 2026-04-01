from fastapi.testclient import TestClient

from app.api.routes_jobs import get_state_service as get_jobs_state_service
from app.api.routes_safety import get_safety_service, get_state_service as get_safety_state_service
from app.main import app
from app.models.records import ScrapedRecord
from app.models.responses import ScrapeResponse
from app.services.safety_case_service import SafetyCaseService
from app.services.state_service import StateService


def _job_with_low_risk() -> ScrapeResponse:
    return ScrapeResponse(
        job_id="job-low-1",
        status="completed",
        plan={},
        records=[
            ScrapedRecord(
                source_url="https://example.com/post/low",
                canonical_url=None,
                record_type="media",
                title="Dog compilation",
                data={"description": "funny dog compilation"},
                images=[],
                videos=[],
                downloaded_images=[],
                confidence=0.5,
                extraction_notes=[],
            )
        ],
        stats={"pages_processed": 1, "records_extracted": 1, "failures": 0, "elapsed_ms": 10},
        warnings=[],
    )


def _job_with_risk() -> ScrapeResponse:
    return ScrapeResponse(
        job_id="job-risk-1",
        status="completed",
        plan={},
        records=[
            ScrapedRecord(
                source_url="https://example.com/post/1",
                canonical_url=None,
                record_type="media",
                title="New in town escort special",
                data={
                    "description": "new in town escort, dm on telegram for details, hotel room tonight",
                    "social_links": ["https://tiktok.com/@example"],
                },
                images=["https://example.com/1.jpg"],
                videos=["https://example.com/1.mp4"],
                downloaded_images=[],
                confidence=0.9,
                extraction_notes=[],
            )
        ],
        stats={"pages_processed": 1, "records_extracted": 1, "failures": 0, "elapsed_ms": 10},
        warnings=[],
    )


def test_create_and_read_safety_case_from_job(tmp_path):
    state = StateService(str(tmp_path))
    safety = SafetyCaseService(str(tmp_path))
    state.save_job(_job_with_risk())

    app.dependency_overrides[get_jobs_state_service] = lambda: state
    app.dependency_overrides[get_safety_state_service] = lambda: state
    app.dependency_overrides[get_safety_service] = lambda: safety

    client = TestClient(app)
    create = client.post(
        "/api/v1/safety/cases/from-job",
        json={"job_id": "job-risk-1", "title": "Investigation case", "min_risk_score": 0.2, "record_limit": 10},
    )
    assert create.status_code == 200
    body = create.json()
    assert body["job_id"] == "job-risk-1"
    assert body["title"] == "Investigation case"
    assert body["flagged_records_count"] >= 1
    assert body["records"][0]["risk_score"] >= 0.2
    assert body["records"][0]["risk_band"] in {"moderate", "high", "critical"}
    assert body["highest_risk_band"] in {"moderate", "high", "critical"}

    list_resp = client.get("/api/v1/safety/cases")
    assert list_resp.status_code == 200
    summaries = list_resp.json()
    assert summaries[0]["case_id"] == body["case_id"]
    assert summaries[0]["highest_risk_band"] == body["highest_risk_band"]
    assert summaries[0]["checklist_total_count"] >= 1
    assert summaries[0]["checklist_completed_count"] == 0
    assert summaries[0]["signoff_approved"] is False

    detail = client.get(f"/api/v1/safety/cases/{body['case_id']}")
    assert detail.status_code == 200
    assert detail.json()["case_id"] == body["case_id"]

    missing_job = client.post("/api/v1/safety/cases/from-job", json={"job_id": "missing"})
    assert missing_job.status_code == 404

    app.dependency_overrides.clear()


def test_get_safety_persona_spec():
    client = TestClient(app)

    response = client.get("/api/v1/safety/persona")
    assert response.status_code == 200

    body = response.json()
    assert body["persona_id"] == "safety-assistant-v1"
    assert "automated safety system" in body["disclosure"].lower()
    assert "minor_risk_terms" in body["risk_rubric"]
    assert "coercion_terms" in body["risk_rubric"]
    assert len(body["first_message_templates"]) >= 3


def test_case_report_package_endpoints(tmp_path):
    state = StateService(str(tmp_path))
    safety = SafetyCaseService(str(tmp_path))
    state.save_job(_job_with_risk())

    app.dependency_overrides[get_jobs_state_service] = lambda: state
    app.dependency_overrides[get_safety_state_service] = lambda: state
    app.dependency_overrides[get_safety_service] = lambda: safety

    client = TestClient(app)
    create = client.post(
        "/api/v1/safety/cases/from-job",
        json={"job_id": "job-risk-1", "title": "Report case", "min_risk_score": 0.2, "record_limit": 10},
    )
    assert create.status_code == 200
    case_id = create.json()["case_id"]

    report = client.get(f"/api/v1/safety/cases/{case_id}/report", params={"reviewer": "analyst-1"})
    assert report.status_code == 200
    report_body = report.json()
    assert report_body["report_id"] == f"report-{case_id}"
    assert report_body["reviewer"] == "analyst-1"
    assert report_body["case_summary"]["case_id"] == case_id
    assert report_body["submission_checklist"]
    assert report_body["submission_checklist"][0]["completed"] is False
    assert report_body["signoff"]["reviewer_id"] == "analyst-1"
    assert report_body["signoff"]["approved"] is False
    assert report_body["signoff"]["destination_channel"] is None
    assert report_body["evidence_manifest"]
    assert report_body["evidence_manifest"][0]["risk_band"] in {"moderate", "high", "critical"}

    download = client.get(f"/api/v1/safety/cases/{case_id}/report.json")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    assert f'safety-case-{case_id}-report.json' in download.headers["content-disposition"]
    assert f'"report_id": "report-{case_id}"' in download.text
    assert '"submission_checklist": [' in download.text
    assert '"signoff": {' in download.text

    missing = client.get("/api/v1/safety/cases/missing-id/report")
    assert missing.status_code == 404

    app.dependency_overrides.clear()


def test_update_case_report_workflow(tmp_path):
    state = StateService(str(tmp_path))
    safety = SafetyCaseService(str(tmp_path))
    state.save_job(_job_with_risk())

    app.dependency_overrides[get_jobs_state_service] = lambda: state
    app.dependency_overrides[get_safety_state_service] = lambda: state
    app.dependency_overrides[get_safety_service] = lambda: safety

    client = TestClient(app)
    create = client.post(
        "/api/v1/safety/cases/from-job",
        json={"job_id": "job-risk-1", "title": "Workflow case", "min_risk_score": 0.2, "record_limit": 10},
    )
    assert create.status_code == 200
    case_id = create.json()["case_id"]

    patch = client.patch(
        f"/api/v1/safety/cases/{case_id}/report/workflow",
        json={
            "checklist_updates": [
                {
                    "item_id": "human-review",
                    "completed": True,
                    "notes": "Primary reviewer completed manual verification.",
                }
            ],
            "signoff": {
                "reviewer_id": "ops-approver",
                "approved": True,
                "destination_channel": "platform-trust-safety",
            },
        },
    )
    assert patch.status_code == 200
    workflow = patch.json()
    assert workflow["case_id"] == case_id
    assert workflow["signoff"]["approved"] is True
    assert workflow["signoff"]["destination_channel"] == "platform-trust-safety"
    assert workflow["signoff"]["approved_at"] is not None
    assert any(
        item["item_id"] == "human-review" and item["completed"] is True
        for item in workflow["submission_checklist"]
    )

    detail = client.get(f"/api/v1/safety/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["signoff"]["approved"] is True

    report = client.get(f"/api/v1/safety/cases/{case_id}/report")
    assert report.status_code == 200
    report_body = report.json()
    assert report_body["signoff"]["approved"] is True
    assert any(
        item["item_id"] == "human-review" and item["completed"] is True
        for item in report_body["submission_checklist"]
    )

    summaries = client.get("/api/v1/safety/cases").json()
    case_summary = next(item for item in summaries if item["case_id"] == case_id)
    assert case_summary["signoff_approved"] is True
    assert case_summary["signoff_reviewer_id"] == "ops-approver"
    assert case_summary["destination_channel"] == "platform-trust-safety"
    assert case_summary["checklist_completed_count"] >= 1

    missing = client.patch("/api/v1/safety/cases/missing-id/report/workflow", json={"checklist_updates": []})
    assert missing.status_code == 404

    app.dependency_overrides.clear()


def test_bulk_workflow_update_and_filters_and_csv(tmp_path):
    state = StateService(str(tmp_path))
    safety = SafetyCaseService(str(tmp_path))
    state.save_job(_job_with_risk())
    state.save_job(_job_with_low_risk())

    app.dependency_overrides[get_jobs_state_service] = lambda: state
    app.dependency_overrides[get_safety_state_service] = lambda: state
    app.dependency_overrides[get_safety_service] = lambda: safety

    client = TestClient(app)
    case1 = client.post(
        "/api/v1/safety/cases/from-job",
        json={"job_id": "job-risk-1", "title": "Bulk one", "min_risk_score": 0.2, "record_limit": 10},
    ).json()["case_id"]
    case2 = client.post(
        "/api/v1/safety/cases/from-job",
        json={"job_id": "job-low-1", "title": "Bulk two", "min_risk_score": 0.0, "record_limit": 10},
    ).json()["case_id"]

    bulk = client.patch(
        "/api/v1/safety/cases/report/workflow/bulk",
        json={
            "case_ids": [case1, case2, "missing-case"],
            "workflow": {
                "checklist_updates": [
                    {"item_id": "human-review", "completed": True, "notes": "bulk done"},
                ],
                "signoff": {
                    "reviewer_id": "bulk-reviewer",
                    "approved": True,
                    "destination_channel": "platform-trust-safety",
                },
            },
        },
    )
    assert bulk.status_code == 200
    body = bulk.json()
    assert case1 in body["updated_case_ids"]
    assert case2 in body["updated_case_ids"]
    assert "missing-case" in body["missing_case_ids"]

    approved = client.get("/api/v1/safety/cases", params={"signoff_approved": "true", "limit": 20})
    assert approved.status_code == 200
    approved_ids = {item["case_id"] for item in approved.json()}
    assert case1 in approved_ids and case2 in approved_ids

    filtered_channel = client.get(
        "/api/v1/safety/cases",
        params={"destination_channel": "platform-trust-safety", "limit": 20},
    )
    assert filtered_channel.status_code == 200
    assert all(item["destination_channel"] == "platform-trust-safety" for item in filtered_channel.json())

    csv = client.get(
        "/api/v1/safety/cases/export.csv",
        params={"signoff_approved": "true", "destination_channel": "platform-trust-safety", "limit": 20},
    )
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=\"safety-cases-summary.csv\"" == csv.headers["content-disposition"]
    assert "case_id,status,job_id,title" in csv.text
    assert "bulk-reviewer" in csv.text

    app.dependency_overrides.clear()
