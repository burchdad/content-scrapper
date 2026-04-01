import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "GhostRescue AI"
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_ingest_creates_entity(client):
    payload = {
        "entities": [
            {
                "canonical_name": "Ana Lucia Perez",
                "entity_type": "person",
                "aliases": ["Ana Perez", "ALP"],
                "source_name": "test_public_records",
            }
        ],
        "source_name": "test_public_records",
    }
    response = await client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["entities_queued"] == 1
    assert data["status"] == "processed"
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_ingest_then_list_entities(client):
    await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Jane Doe", "source_name": "test"}],
            "source_name": "test",
        },
    )
    response = await client.get("/api/v1/entities")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["entities"][0]["canonical_name"] == "Jane Doe"
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_get_entity_by_id(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Carlos Mendez", "aliases": ["C.M."], "source_name": "test"}],
            "source_name": "test",
        },
    )
    assert ingest.status_code == 200

    list_resp = await client.get("/api/v1/entities")
    entity_id = list_resp.json()["entities"][0]["entity_id"]

    get_resp = await client.get(f"/api/v1/entities/{entity_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["entity_id"] == entity_id


@pytest.mark.asyncio
async def test_get_entity_not_found(client):
    response = await client.get("/api/v1/entities/nonexistent-entity-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analyze_detects_signals(client):
    response = await client.post(
        "/api/v1/analyze",
        json={
            "text": "She was forced and had no choice. Contact me on telegram only.",
            "source_name": "test",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["risk_score"] >= 0
    assert "disclaimer" in data
    signal_types = [s["signal_type"] for s in data["signals"]]
    assert "coercion_language" in signal_types
    assert "off_platform_contact" in signal_types


@pytest.mark.asyncio
async def test_analyze_clean_text_zero_score(client):
    response = await client.post(
        "/api/v1/analyze",
        json={"text": "The weather is nice today. She bought fruit at the market."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["risk_score"] == 0.0
    assert data["signals"] == []


@pytest.mark.asyncio
async def test_ingest_deduplication(client):
    """Same canonical name submitted twice should resolve to same entity."""
    body = {
        "entities": [{"canonical_name": "Rosa Maria Santos", "source_name": "src1"}],
        "source_name": "src1",
    }
    await client.post("/api/v1/ingest", json=body)
    body["entities"][0]["source_name"] = "src2"
    await client.post("/api/v1/ingest", json=body)

    list_resp = await client.get("/api/v1/entities")
    # Should be 1 entity (merged/linked), not 2
    assert list_resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_alerts_empty(client):
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["alerts"] == []


@pytest.mark.asyncio
async def test_entity_timeline_and_correlations(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Timeline Person", "aliases": ["TP"], "source_name": "source-a"}],
            "source_name": "source-a",
            "source_url": "https://public.example/a",
        },
    )
    assert ingest.status_code == 200
    entity_id = ingest.json()["resolved_entity_ids"][0]

    timeline = await client.get(f"/api/v1/entities/{entity_id}/timeline")
    assert timeline.status_code == 200
    t = timeline.json()
    assert t["entity_id"] == entity_id
    assert t["total"] >= 1
    assert t["events"][0]["event_type"] in {"ingested", "analysis", "case_evaluated"}

    corr = await client.get(f"/api/v1/entities/{entity_id}/correlations")
    assert corr.status_code == 200
    c = corr.json()
    assert c["entity_id"] == entity_id
    assert c["found"] is True
    assert c["event_count"] >= 1


@pytest.mark.asyncio
async def test_analyze_creates_case_and_alert(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Alert Person", "source_name": "source-a"}],
            "source_name": "source-a",
        },
    )
    entity_id = ingest.json()["resolved_entity_ids"][0]

    analyze = await client.post(
        "/api/v1/analyze",
        json={
            "entity_id": entity_id,
            "text": "Underage victim was forced and controlled. Contact on telegram only.",
            "source_name": "source-b",
            "source_url": "https://public.example/post-1",
        },
    )
    assert analyze.status_code == 200
    data = analyze.json()
    assert data["case_id"] is not None
    assert data["risk_score"] >= 45.0
    assert 0.0 <= data["system_confidence"] <= 1.0

    alerts = await client.get("/api/v1/alerts")
    assert alerts.status_code == 200
    alert_data = alerts.json()
    assert alert_data["total"] >= 1

    case_resp = await client.get(f"/api/v1/cases/{data['case_id']}")
    assert case_resp.status_code == 200
    case_json = case_resp.json()
    assert case_json["status"] in {"under_review", "escalated"}


@pytest.mark.asyncio
async def test_case_evaluate_and_summary(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Case Eval Person", "source_name": "source-c"}],
            "source_name": "source-c",
        },
    )
    entity_id = ingest.json()["resolved_entity_ids"][0]

    evaluated = await client.post(
        "/api/v1/cases/evaluate",
        json={
            "entity_id": entity_id,
            "text": "Recruitment pitch promised easy money and outcall escort work.",
            "source_name": "source-d",
        },
    )
    assert evaluated.status_code == 200
    case = evaluated.json()
    assert case["case_id"].startswith("case-")

    listing = await client.get("/api/v1/cases")
    assert listing.status_code == 200
    l = listing.json()
    assert l["total"] >= 1
    assert len(l["cases"]) >= 1

    summary = await client.get(f"/api/v1/cases/{case['case_id']}/summary")
    assert summary.status_code == 200
    s = summary.json()
    assert s["case_id"] == case["case_id"]
    assert "automated triage indicators" in s["narrative"].lower()
    assert 0.0 <= s["system_confidence"] <= 1.0
    assert "disclaimer" in s
