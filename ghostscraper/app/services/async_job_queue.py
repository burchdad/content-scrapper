import asyncio
import logging

from app.models.requests import ScrapeRequest
from app.models.responses import JobDiagnostics, JobWarning, ScrapeResponse
from app.services.scrape_orchestrator import ScrapeOrchestrator
from app.services.state_service import StateService

logger = logging.getLogger(__name__)


class AsyncJobQueue:
    """In-process FIFO queue for background scrape jobs."""

    def __init__(self, orchestrator: ScrapeOrchestrator, state: StateService, maxsize: int = 100) -> None:
        self.orchestrator = orchestrator
        self.state = state
        self.queue: asyncio.Queue[tuple[str, ScrapeRequest]] = asyncio.Queue(maxsize=maxsize)
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker(), name="ghostscraper-async-worker")

    async def stop(self) -> None:
        if not self._worker_task:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass

    async def enqueue(self, request: ScrapeRequest) -> str:
        job_id = self.state.create_status_job(job_id=None, status="queued")
        await self.queue.put((job_id, request))
        return job_id

    async def _worker(self) -> None:
        while True:
            job_id, request = await self.queue.get()
            try:
                self.state.create_status_job(job_id=job_id, status="running")
                response = await self.orchestrator.run_scrape_job(request, job_id=job_id)
                self.state.save_job(response)
            except Exception as exc:
                logger.exception("job.failed", extra={"job_id": job_id})
                failed = ScrapeResponse(
                    job_id=job_id,
                    status="failed",
                    plan={},
                    records=[],
                    stats={"pages_processed": 0, "records_extracted": 0, "failures": 1, "elapsed_ms": 0},
                    warnings=[JobWarning(code="JOB_FAILED", message=str(exc))],
                    diagnostics=JobDiagnostics(
                        primary_issue="JOB_FAILED",
                        recommendation="Check warning details and retry with fewer pages or static mode.",
                        warning_counts={"JOB_FAILED": 1},
                    ),
                )
                self.state.save_job(failed)
            finally:
                self.queue.task_done()
