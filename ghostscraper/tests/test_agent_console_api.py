from fastapi.testclient import TestClient

from app.main import app


class FakeQueue:
    async def enqueue(self, request):
        return "queued-job-xyz"


def test_agent_console_presets_and_history_submit_flow(tmp_path):
    client = TestClient(app)
    app.state.job_queue = FakeQueue()

    preset_payload = {
        "user_id": "alice",
        "name": "Trend preset",
        "request": {
            "query": "collect trend videos",
            "mode": "auto",
            "max_pages": 5,
            "source_pack_ids": ["short-video-viral", "meme-gif-culture"],
        },
    }
    created = client.post("/api/v1/agent/presets", json=preset_payload)
    assert created.status_code == 200
    preset_id = created.json()["preset_id"]

    listed = client.get("/api/v1/agent/presets", params={"user_id": "alice"})
    assert listed.status_code == 200
    assert len(listed.json()) >= 1

    submit = client.post(
        "/api/v1/agent/history/submit",
        json={
            "user_id": "alice",
            "label": "Run trend scrape",
            "run_async": True,
            "request": {
                "query": "collect trend videos",
                "mode": "auto",
                "max_pages": 5,
                "source_pack_ids": ["short-video-viral", "social-discussion"],
            },
        },
    )
    assert submit.status_code == 200
    body = submit.json()
    assert body["job_id"] == "queued-job-xyz"
    history_id = body["history_id"]

    history = client.get("/api/v1/agent/history", params={"user_id": "alice"})
    assert history.status_code == 200
    assert history.json()[0]["history_id"] == history_id

    rerun = client.post(
        f"/api/v1/agent/history/{history_id}/rerun",
        params={"user_id": "alice", "run_async": "true"},
    )
    assert rerun.status_code == 200
    assert rerun.json()["job_id"] == "queued-job-xyz"

    deleted = client.delete(f"/api/v1/agent/presets/{preset_id}", params={"user_id": "alice"})
    assert deleted.status_code == 200


def test_source_pack_catalog_endpoint_lists_curated_packs():
    client = TestClient(app)

    response = client.get("/api/v1/source-packs")

    assert response.status_code == 200
    packs = response.json()
    assert any(pack["pack_id"] == "short-video-viral" for pack in packs)
    assert any(pack["pack_id"] == "news-wires" for pack in packs)


def test_agent_history_supports_offset_pagination():
    client = TestClient(app)
    app.state.job_queue = FakeQueue()

    for i in range(3):
        submit = client.post(
            "/api/v1/agent/history/submit",
            json={
                "user_id": "offset-user",
                "label": f"run-{i}",
                "run_async": True,
                "request": {
                    "query": f"collect trend videos {i}",
                    "mode": "auto",
                    "max_pages": 2,
                },
            },
        )
        assert submit.status_code == 200

    page1 = client.get("/api/v1/agent/history", params={"user_id": "offset-user", "limit": 2, "offset": 0})
    assert page1.status_code == 200
    assert len(page1.json()) == 2

    page2 = client.get("/api/v1/agent/history", params={"user_id": "offset-user", "limit": 2, "offset": 2})
    assert page2.status_code == 200
    assert len(page2.json()) >= 1


def test_agent_history_delete_entry():
    client = TestClient(app)
    app.state.job_queue = FakeQueue()

    submit = client.post(
        "/api/v1/agent/history/submit",
        json={
            "user_id": "delete-user",
            "label": "delete me",
            "run_async": True,
            "request": {
                "query": "collect trend videos",
                "mode": "auto",
                "max_pages": 2,
            },
        },
    )
    assert submit.status_code == 200
    history_id = submit.json()["history_id"]

    deleted = client.delete(f"/api/v1/agent/history/{history_id}", params={"user_id": "delete-user"})
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    remaining = client.get("/api/v1/agent/history", params={"user_id": "delete-user"})
    assert remaining.status_code == 200
    assert all(item["history_id"] != history_id for item in remaining.json())


def test_agent_history_delete_missing_returns_404():
    client = TestClient(app)

    response = client.delete("/api/v1/agent/history/missing-id", params={"user_id": "default"})
    assert response.status_code == 404


def test_create_safety_default_preset():
    client = TestClient(app)

    response = client.post(
        "/api/v1/agent/presets/safety-default",
        json={
            "user_id": "safety-user",
            "query": "monitor grooming language in public comments",
            "include_mature_content": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Safety Monitoring Preset"
    assert body["request"]["query"] == "monitor grooming language in public comments"
    assert body["request"]["include_mature_content"] is True
    assert "social-discussion" in (body["request"].get("source_pack_ids") or [])
