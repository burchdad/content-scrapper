import pytest


@pytest.mark.asyncio
async def test_trust_config_get_and_patch(client):
    get_resp = await client.get("/api/v1/trust/config")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert cfg["risk_high_threshold"] >= 0

    patch_resp = await client.patch(
        "/api/v1/trust/config",
        json={
            "risk_medium_threshold": 40.0,
            "risk_high_threshold": 60.0,
            "risk_critical_threshold": 78.0,
            "cluster_similarity_threshold": 0.55,
            "false_positive_penalty": 0.2,
        },
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["risk_medium_threshold"] == 40.0
    assert patched["cluster_similarity_threshold"] == 0.55


@pytest.mark.asyncio
async def test_feedback_loop_and_stats(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [{"canonical_name": "Feedback Person", "source_name": "src-a"}],
            "source_name": "src-a",
        },
    )
    entity_id = ingest.json()["resolved_entity_ids"][0]

    case_eval = await client.post(
        "/api/v1/cases/evaluate",
        json={
            "entity_id": entity_id,
            "text": "Underage and forced language with telegram contact.",
            "source_name": "src-b",
        },
    )
    assert case_eval.status_code == 200
    case_id = case_eval.json()["case_id"]

    fb = await client.post(
        "/api/v1/trust/feedback",
        json={
            "case_id": case_id,
            "analyst_id": "analyst-1",
            "is_false_positive": True,
            "corrected_risk_score": 20.0,
            "notes": "Overflagged due to context.",
        },
    )
    assert fb.status_code == 200
    assert fb.json()["is_false_positive"] is True

    listed = await client.get("/api/v1/trust/feedback")
    assert listed.status_code == 200
    assert len(listed.json()) >= 1

    stats = await client.get("/api/v1/trust/stats")
    assert stats.status_code == 200
    s = stats.json()
    assert s["total_feedback"] >= 1
    assert 0.0 <= s["false_positive_rate"] <= 1.0
    assert 0.0 <= s["adaptive_penalty"] <= 1.0


@pytest.mark.asyncio
async def test_case_clusters_endpoint(client):
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "entities": [
                {"canonical_name": "Cluster One", "source_name": "src-1"},
                {"canonical_name": "Cluster Two", "source_name": "src-2"},
            ],
            "source_name": "src-multi",
        },
    )
    ids = ingest.json()["resolved_entity_ids"]

    await client.post(
        "/api/v1/cases/evaluate",
        json={
            "entity_id": ids[0],
            "text": "Recruitment language and easy money offer via telegram.",
            "source_name": "src-3",
        },
    )
    await client.post(
        "/api/v1/cases/evaluate",
        json={
            "entity_id": ids[1],
            "text": "Recruitment language and easy money offer via telegram.",
            "source_name": "src-4",
        },
    )

    clusters = await client.get("/api/v1/cases/clusters")
    assert clusters.status_code == 200
    payload = clusters.json()
    assert payload["total_clusters"] >= 1
    assert len(payload["clusters"]) >= 1
