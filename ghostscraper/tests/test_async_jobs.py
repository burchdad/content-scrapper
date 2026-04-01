from fastapi.testclient import TestClient

from app.api.routes_jobs import get_job_queue
from app.main import app


class FakeQueue:
    def __init__(self):
        self.calls = 0
        self.last_request = None

    async def enqueue(self, request):
        self.calls += 1
        self.last_request = request
        return "queued-job-123"


def test_scrape_async_endpoint_accepts_job():
    fake_queue = FakeQueue()
    app.dependency_overrides[get_job_queue] = lambda: fake_queue

    client = TestClient(app)
    payload = {
        "query": "scrape product pricing pages",
        "mode": "auto",
    }

    response = client.post("/api/v1/jobs/scrape/async", json=payload)

    assert response.status_code == 200
    assert response.json() == {"job_id": "queued-job-123", "status": "queued"}
    assert fake_queue.calls == 1
    assert fake_queue.last_request.source_pack_ids is None

    app.dependency_overrides.clear()


def test_scrape_async_endpoint_accepts_source_pack_ids():
    fake_queue = FakeQueue()
    app.dependency_overrides[get_job_queue] = lambda: fake_queue

    client = TestClient(app)
    payload = {
        "query": "scrape creator economy trends",
        "mode": "auto",
        "source_pack_ids": ["short-video-viral", "social-discussion"],
    }

    response = client.post("/api/v1/jobs/scrape/async", json=payload)

    assert response.status_code == 200
    assert response.json() == {"job_id": "queued-job-123", "status": "queued"}
    assert fake_queue.last_request.source_pack_ids == ["short-video-viral", "social-discussion"]

    app.dependency_overrides.clear()
