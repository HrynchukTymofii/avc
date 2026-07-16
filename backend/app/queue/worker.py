"""The single sequential GPU worker.

One asyncio task drains one asyncio.Queue of job IDs. A job failure of any kind
(exception, timeout, missing processor) is converted into FAILED job state and
the loop continues — only task cancellation (server shutdown) exits the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from app.queue.job import Job, JobState, utc_now
from app.queue.job_store import JobStore
from app.schemas import JobKind

log = logging.getLogger(__name__)

ProgressReporter = Callable[[int, str], None]
"""(progress 0-100, stage) -> None. Safe to call from any thread."""

FailureHook = Callable[[BaseException], Awaitable[None]]
"""Called after a job fails or times out — used for GPU cleanup (cache clearing,
post-OOM offloading). Not called on server shutdown."""


class JobProcessor(Protocol):
    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        """Run the job and return its outputs dict (URL paths). Raises on failure."""
        ...


class GPUWorker:
    def __init__(
        self,
        store: JobStore,
        processors: Mapping[JobKind, JobProcessor],
        job_timeout_s: float,
        failure_hook: FailureHook | None = None,
        timeout_overrides: Mapping[JobKind, float] | None = None,
    ) -> None:
        self._store = store
        self._processors = dict(processors)
        self._job_timeout_s = job_timeout_s
        self._timeout_overrides = dict(timeout_overrides or {})
        self._failure_hook = failure_hook
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.current_job_id: str | None = None

    def register_processor(self, kind: JobKind, processor: JobProcessor) -> None:
        self._processors[kind] = processor

    async def submit(self, job: Job) -> None:
        self._store.add(job)
        self._queue.put_nowait(job.id)
        log.info(
            "job submitted",
            extra={"job_id": job.id, "kind": job.kind.value, "label": job.label},
        )

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("worker already started")
        self._task = asyncio.create_task(self._run(), name="gpu-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        log.info("gpu worker started", extra={"job_timeout_s": self._job_timeout_s})
        while True:
            job_id = await self._queue.get()
            try:
                await self._process_one(job_id)
            finally:
                self.current_job_id = None
                self._queue.task_done()

    async def _process_one(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if job is None:
            log.warning("dequeued unknown job id", extra={"job_id": job_id})
            return

        self.current_job_id = job_id
        self._store.update(job_id, state=JobState.PROCESSING, started_at=utc_now(), progress=0)
        log.info("job started", extra={"job_id": job_id, "kind": job.kind.value})

        loop = asyncio.get_running_loop()

        def report(progress: int, stage: str) -> None:
            # Marshals onto the event loop so the store is only touched from there;
            # processors may call this from their inference worker thread.
            loop.call_soon_threadsafe(self._apply_progress, job_id, progress, stage)

        timeout_s = self._timeout_overrides.get(job.kind, self._job_timeout_s)
        try:
            processor = self._processors.get(job.kind)
            if processor is None:
                raise RuntimeError(f"no processor registered for job kind {job.kind.value!r}")
            outputs = await asyncio.wait_for(
                processor.process(job, report), timeout=timeout_s
            )
        except asyncio.CancelledError:
            self._store.update(
                job_id,
                state=JobState.FAILED,
                error="Server shut down during processing",
                finished_at=utc_now(),
            )
            raise  # shutdown must propagate — never swallow cancellation
        except TimeoutError as exc:
            self._store.update(
                job_id,
                state=JobState.FAILED,
                error=f"Job exceeded the {timeout_s:.0f} second time limit",
                finished_at=utc_now(),
            )
            log.error("job timed out", extra={"job_id": job_id})
            await self._run_failure_hook(exc)
        except Exception as exc:
            self._store.update(
                job_id,
                state=JobState.FAILED,
                error=_user_message(exc),
                finished_at=utc_now(),
            )
            log.exception("job failed", extra={"job_id": job_id})
            await self._run_failure_hook(exc)
        else:
            finished_at = utc_now()
            self._store.update(
                job_id,
                state=JobState.FINISHED,
                outputs=outputs,
                progress=100,
                finished_at=finished_at,
            )
            duration = (finished_at - job.started_at).total_seconds() if job.started_at else None
            log.info("job finished", extra={"job_id": job_id, "duration_s": duration})

    async def _run_failure_hook(self, exc: BaseException) -> None:
        if self._failure_hook is None:
            return
        try:
            await self._failure_hook(exc)
        except Exception:
            # Cleanup best-effort only — a failing hook must never take the worker down.
            log.exception("failure hook raised")

    def _apply_progress(self, job_id: str, progress: int, stage: str) -> None:
        job = self._store.get(job_id)
        # Ignore late callbacks from a job that already finished, failed, or timed out.
        if job is None or job.state is not JobState.PROCESSING:
            return
        self._store.update(job_id, progress=max(0, min(100, progress)), stage=stage)


def _user_message(exc: Exception) -> str:
    return str(exc).strip() or f"{type(exc).__name__} (no details)"
