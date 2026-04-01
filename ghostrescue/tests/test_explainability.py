"""Tests for explainability service and endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.case import Case
from app.models.signal import Signal
from app.models.feedback import AnalystFeedback
from app.services.explainability_service import ExplainabilityService


@pytest.mark.asyncio
async def test_explainability_service_case_not_found(db_session: AsyncSession):
    """Test explainability service returns error for non-existent case."""
    service = ExplainabilityService(db_session)
    result = await service.case_explainability("nonexistent-case")
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_explainability_json_endpoint_not_found(client: AsyncClient):
    """Test explainability JSON endpoint returns 404 for non-existent case."""
    response = await client.get("/api/v1/cases/nonexistent-case/explainability")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_explainability_service_with_signals(db_session: AsyncSession):
    """Test explainability service computes correct signal contributions."""
    # Create a case with signals
    case = Case(
        case_id="case-test-explain-001",
        status="open",
        risk_score=75.5,
        confidence_score=0.85,
        system_confidence=0.82,
        explanation="Test case with multiple signals",
        signal_ids=["sig-1", "sig-2"],
        entity_ids=["ent-1"],
    )
    db_session.add(case)

    # Create signals
    sig1 = Signal(
        signal_id="sig-1",
        signal_type="coercion",
        label="Coercive language detected",
        confidence=0.9,
        evidence="You must do this or else...",
    )
    sig2 = Signal(
        signal_id="sig-2",
        signal_type="minor_risk",
        label="Minor risk language",
        confidence=0.6,
        evidence="Some minor indicator",
    )
    db_session.add(sig1)
    db_session.add(sig2)
    await db_session.commit()

    # Get explainability
    service = ExplainabilityService(db_session)
    result = await service.case_explainability("case-test-explain-001")

    assert result["case_id"] == "case-test-explain-001"
    assert result["risk_score"] == 75.5
    assert result["system_confidence"] == 0.82
    assert result["signal_count"] == 2
    assert len(result["signal_contributions"]) == 2

    # Verify signal weights sum to ~100%
    total_weight = sum(sig["weight_pct"] for sig in result["signal_contributions"])
    assert 99.0 < total_weight <= 100.5  # allow small rounding error


@pytest.mark.asyncio
async def test_explainability_service_with_feedback(db_session: AsyncSession):
    """Test explainability service includes feedback summary."""
    # Create a case
    case = Case(
        case_id="case-test-fb-001",
        status="open",
        risk_score=50.0,
        confidence_score=0.75,
        system_confidence=0.70,
        explanation="Test case with feedback",
        signal_ids=[],
        entity_ids=[],
    )
    db_session.add(case)
    await db_session.commit()

    # Add feedback records
    fb1 = AnalystFeedback(
        feedback_id="fb-1",
        case_id="case-test-fb-001",
        analyst_id="analyst_alice",
        is_false_positive=False,
        corrected_risk_score=55.0,
        notes="Confirmed trafficking indicators",
    )
    fb2 = AnalystFeedback(
        feedback_id="fb-2",
        case_id="case-test-fb-001",
        analyst_id="analyst_bob",
        is_false_positive=True,
        corrected_risk_score=10.0,
        notes="Actually benign outreach",
    )
    db_session.add(fb1)
    db_session.add(fb2)
    await db_session.commit()

    # Get explainability
    service = ExplainabilityService(db_session)
    result = await service.case_explainability("case-test-fb-001")

    feedback_summary = result["feedback_summary"]
    assert feedback_summary["feedback_count"] == 2
    assert feedback_summary["false_positive_count"] == 1
    assert feedback_summary["false_positive_rate"] == 0.5
    assert feedback_summary["avg_corrected_risk_score"] == 32.5  # (55 + 10) / 2
    assert len(feedback_summary["recent_feedback"]) == 2


@pytest.mark.asyncio
async def test_explainability_html_endpoint(client: AsyncClient):
    """Test explainability HTML endpoint returns valid HTML."""
    # First create a case via the analyze endpoint
    ingest_resp = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [
                {
                    "canonical_name": "HTML Test Person",
                    "entity_type": "person",
                    "aliases": [],
                    "source_name": "test_source",
                }
            ],
            "source_name": "test_source",
        },
    )
    assert ingest_resp.status_code == 200

    # Analyze text to create case
    analyze_resp = await client.post(
        "/api/v1/analyze",
        json={
            "text": "You will work or I will hurt you and your family. Contact me off platform.",
            "entity_id": ingest_resp.json()["resolved_entity_ids"][0],
        },
    )
    assert analyze_resp.status_code == 200
    case_id = analyze_resp.json()["case_id"]

    # Get HTML explainability
    html_resp = await client.get(f"/api/v1/cases/{case_id}/explainability/html")
    assert html_resp.status_code == 200
    html_content = html_resp.text

    # Verify HTML structure
    assert "<html>" in html_content or "<HTML>" in html_content.upper()
    assert "Explainability" in html_content
    assert "Signal Contributions" in html_content
    assert "Confidence Composition" in html_content
    assert "Analyst Feedback" in html_content
    assert case_id in html_content


@pytest.mark.asyncio
async def test_explainability_json_endpoint_with_case(client: AsyncClient):
    """Test explainability JSON endpoint returns properly formatted response."""
    # Create a case
    ingest_resp = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [
                {
                    "canonical_name": "JSON Test Person",
                    "entity_type": "person",
                    "aliases": [],
                    "source_name": "test_source",
                }
            ],
            "source_name": "test_source",
        },
    )
    entity_id = ingest_resp.json()["resolved_entity_ids"][0]

    # Analyze to create case
    analyze_resp = await client.post(
        "/api/v1/analyze",
        json={
            "text": "I will force you into commercial sex work. Pay me now.",
            "entity_id": entity_id,
        },
    )
    case_id = analyze_resp.json()["case_id"]

    # Get JSON explainability
    json_resp = await client.get(f"/api/v1/cases/{case_id}/explainability")
    assert json_resp.status_code == 200
    data = json_resp.json()

    # Verify response structure
    assert data["case_id"] == case_id
    assert "case_status" in data
    assert "risk_score" in data
    assert "system_confidence" in data
    assert isinstance(data["system_confidence"], (int, float))
    assert 0.0 <= data["system_confidence"] <= 1.0

    # Verify signal contributions structure
    assert "signal_contributions" in data
    for sig in data["signal_contributions"]:
        assert "signal_type" in sig
        assert "label" in sig
        assert "confidence" in sig
        assert "weight_pct" in sig
        assert 0.0 <= sig["confidence"] <= 1.0

    # Verify confidence breakdown structure
    cb = data["confidence_breakdown"]
    assert "signal_avg" in cb
    assert "entity_confidence" in cb
    assert "diversity_bonus" in cb
    assert "calibration_penalty" in cb
    assert "final_system_confidence" in cb

    # Verify feedback summary structure
    fb = data["feedback_summary"]
    assert "feedback_count" in fb
    assert "false_positive_rate" in fb
    assert "recent_feedback" in fb

    # Verify trust config context
    tcp = data["trust_config_context"]
    assert "risk_medium_threshold" in tcp
    assert "risk_high_threshold" in tcp
    assert "risk_critical_threshold" in tcp


@pytest.mark.asyncio
async def test_feedback_history_endpoint(client: AsyncClient):
    """Test feedback history endpoint."""
    # Create case with feedback
    ingest_resp = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [
                {
                    "canonical_name": "History Test Person",
                    "entity_type": "person",
                    "aliases": [],
                }
            ],
        },
    )
    entity_id = ingest_resp.json()["resolved_entity_ids"][0]

    # Create case
    case_resp = await client.post(
        "/api/v1/cases/evaluate",
        json={
            "text": "Pay me or I will harm you.",
            "entity_id": entity_id,
        },
    )
    case_id = case_resp.json()["case_id"]

    # Add feedback
    fb_resp = await client.post(
        "/api/v1/trust/feedback",
        json={
            "case_id": case_id,
            "analyst_id": "test_analyst",
            "is_false_positive": False,
            "corrected_risk_score": 65.0,
            "notes": "Legitimate trafficking case",
        },
    )
    assert fb_resp.status_code == 200

    # Get feedback history
    history_resp = await client.get(f"/api/v1/cases/{case_id}/explainability/feedback")
    assert history_resp.status_code == 200
    history = history_resp.json()

    assert history["case_id"] == case_id
    assert history["days"] == 30
    assert history["feedback_count"] >= 1
    assert "history" in history
    assert len(history["history"]) >= 1


@pytest.mark.asyncio
async def test_confidence_breakdown_computation(db_session: AsyncSession):
    """Test that confidence breakdown is computed correctly."""
    # Create case with known confidence formula components
    case = Case(
        case_id="case-conf-test",
        status="open",
        risk_score=80.0,
        confidence_score=0.9,
        system_confidence=0.85,
        explanation="Confidence test case",
        signal_ids=["sig-conf-1", "sig-conf-2"],
        entity_ids=[],
    )
    db_session.add(case)

    # Create signals with known confidences
    sig1 = Signal(
        signal_id="sig-conf-1",
        signal_type="coercion",
        label="Test signal 1",
        confidence=0.95,
        evidence="Evidence 1",
    )
    sig2 = Signal(
        signal_id="sig-conf-2",
        signal_type="recruitment",
        label="Test signal 2",
        confidence=0.85,
        evidence="Evidence 2",
    )
    db_session.add(sig1)
    db_session.add(sig2)
    await db_session.commit()

    service = ExplainabilityService(db_session)
    result = await service.case_explainability("case-conf-test")

    cb = result["confidence_breakdown"]
    # Average confidence should be (0.95 + 0.85) / 2 = 0.9
    assert abs(cb["signal_avg"] - 0.9) < 0.01
