from fastapi.testclient import TestClient

from app.api.routes_jobs import get_state_service
from app.main import app
from app.models.records import ScrapedRecord
from app.models.responses import ScrapeResponse
from app.services.state_service import StateService


def _make_export_job() -> ScrapeResponse:
    return ScrapeResponse(
        job_id="job-export-1",
        status="completed",
        plan={},
        records=[
            ScrapedRecord(
                source_url="https://example.com/a",
                canonical_url=None,
                record_type="products",
                title="Widget A",
                data={"price": 19.99, "sku": "W-A", "address": "ignore-me"},
                images=["https://example.com/a.jpg", "https://example.com/b.jpg"],
                downloaded_images=[],
                confidence=0.81,
                extraction_notes=[],
            )
        ],
        stats={"pages_processed": 1, "records_extracted": 1, "failures": 0, "elapsed_ms": 10},
        warnings=[],
    )


def test_export_csv_endpoint_and_ui_route(tmp_path):
    state = StateService(str(tmp_path))
    state.save_job(_make_export_job())

    app.dependency_overrides[get_state_service] = lambda: state
    client = TestClient(app)

    csv_response = client.get("/api/v1/jobs/job-export-1/export.csv", params={"fields": "title,price,sku"})
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=\"job-export-1.csv\"" == csv_response.headers["content-disposition"]
    assert "Widget A" in csv_response.text
    assert "price" in csv_response.text
    assert "sku" in csv_response.text
    assert "address" not in csv_response.text

    missing_csv = client.get("/api/v1/jobs/missing/export.csv")
    assert missing_csv.status_code == 404

    ui_response = client.get("/ui/jobs")
    assert ui_response.status_code == 200
    assert "GhostScraper Jobs Browser" in ui_response.text
    assert "Trend Pull Preset" in ui_response.text
    assert "Run Job" in ui_response.text
    assert "Create Safety Case" in ui_response.text
    assert "thumbnail-strip" in ui_response.text
    assert "video-strip" in ui_response.text
    assert "renderEmbeds" in ui_response.text
    assert "/api/v1/jobs/" in ui_response.text

    agent_ui = client.get("/ui/agent")
    assert agent_ui.status_code == 200
    assert "GhostScraper Agent Console" in agent_ui.text
    assert "Saved Presets" in agent_ui.text
    assert "Save Safety Preset" in agent_ui.text
    assert "Safety Persona" in agent_ui.text
    assert "Case Board" in agent_ui.text
    assert "Apply Case Filters" in agent_ui.text
    assert "Download Case CSV" in agent_ui.text
    assert "Bulk Mark Human Review" in agent_ui.text
    assert "Bulk Approve" in agent_ui.text
    assert "/api/v1/safety/cases/" in agent_ui.text
    assert "/report.json" in agent_ui.text
    assert "Mark Human Review Done" in agent_ui.text
    assert "Approve + Sign Off" in agent_ui.text
    assert "/report/workflow" in agent_ui.text
    assert "/report/workflow/bulk" in agent_ui.text
    assert "/cases/export.csv" in agent_ui.text
    assert "checklist" in agent_ui.text
    assert "channel:" in agent_ui.text
    assert "Open concise run summary" in agent_ui.text

    app.dependency_overrides.clear()