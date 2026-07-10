"""Queue core: ordering, positions, crash isolation, timeout, persistence, shutdown."""

import asyncio
import json

import pytest

from app.queue.job import Job, JobState
from app.queue.job_store import JobStore
from app.queue.worker import GPUWorker, ProgressReporter
from app.schemas import JobKind
from tests.conftest import make_job, wait_for_state


class GatedProcessor:
    """Holds each job until released; records processing order."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started: list[str] = []

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        self.started.append(job.id)
        await self.release.wait()
        report(100, "done")
        return {"video": f"/outputs/{job.id}/output.mp4"}


class FlakyProcessor:
    """Crashes jobs labelled 'crash', succeeds otherwise."""

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        if job.label == "crash":
            raise ValueError("synthetic model failure")
        report(50, "halfway")
        return {"video": f"/outputs/{job.id}/output.mp4"}


class HangingProcessor:
    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        await asyncio.sleep(60)
        return {}


async def test_sequential_order_and_queue_positions(store: JobStore) -> None:
    processor = GatedProcessor()
    worker = GPUWorker(store, {JobKind.BROLL: processor}, job_timeout_s=10)
    worker.start()
    try:
        jobs = [make_job(f"job-{i}") for i in range(3)]
        for job in jobs:
            await worker.submit(job)

        # job 0 gets picked up; jobs 1 and 2 wait in line
        await wait_for_state(store, jobs[0].id, JobState.PROCESSING)
        assert store.queued_position(jobs[0].id) is None
        assert store.queued_position(jobs[1].id) == 1
        assert store.queued_position(jobs[2].id) == 2

        processor.release.set()
        for job in jobs:
            finished = await wait_for_state(store, job.id, JobState.FINISHED)
            assert finished.outputs["video"].endswith("output.mp4")

        assert processor.started == [j.id for j in jobs]  # strict FIFO
    finally:
        await worker.stop()


async def test_crash_does_not_kill_worker(store: JobStore) -> None:
    worker = GPUWorker(store, {JobKind.BROLL: FlakyProcessor()}, job_timeout_s=10)
    worker.start()
    try:
        crashing = make_job("crash")
        healthy = make_job("healthy")
        await worker.submit(crashing)
        await worker.submit(healthy)

        failed = await wait_for_state(store, crashing.id, JobState.FAILED)
        assert failed.error == "synthetic model failure"

        finished = await wait_for_state(store, healthy.id, JobState.FINISHED)
        assert finished.state is JobState.FINISHED
        assert finished.progress == 100
    finally:
        await worker.stop()


async def test_missing_processor_fails_job_not_worker(store: JobStore) -> None:
    worker = GPUWorker(store, {JobKind.BROLL: FlakyProcessor()}, job_timeout_s=10)
    worker.start()
    try:
        orphan = make_job("orphan", kind=JobKind.TALKING_HEAD)
        healthy = make_job("healthy")
        await worker.submit(orphan)
        await worker.submit(healthy)

        failed = await wait_for_state(store, orphan.id, JobState.FAILED)
        assert "no processor registered" in (failed.error or "")
        await wait_for_state(store, healthy.id, JobState.FINISHED)
    finally:
        await worker.stop()


async def test_timeout_fails_job_and_continues(store: JobStore) -> None:
    worker = GPUWorker(
        store,
        {JobKind.BROLL: HangingProcessor(), JobKind.TALKING_HEAD: FlakyProcessor()},
        job_timeout_s=0.2,
    )
    worker.start()
    try:
        hung = make_job("hung")
        healthy = make_job("healthy", kind=JobKind.TALKING_HEAD)
        await worker.submit(hung)
        await worker.submit(healthy)

        failed = await wait_for_state(store, hung.id, JobState.FAILED)
        assert "time limit" in (failed.error or "")
        await wait_for_state(store, healthy.id, JobState.FINISHED)
    finally:
        await worker.stop()


async def test_progress_reporting(store: JobStore) -> None:
    processor = GatedProcessor()
    worker = GPUWorker(store, {JobKind.BROLL: processor}, job_timeout_s=10)
    worker.start()
    try:
        job = make_job()
        await worker.submit(job)
        await wait_for_state(store, job.id, JobState.PROCESSING)

        # report from the event loop thread while the job is held open
        loop_job = store.get(job.id)
        assert loop_job is not None and loop_job.progress == 0

        processor.release.set()
        finished = await wait_for_state(store, job.id, JobState.FINISHED)
        assert finished.progress == 100
    finally:
        await worker.stop()


async def test_shutdown_marks_inflight_job_failed(store: JobStore) -> None:
    processor = GatedProcessor()  # never released
    worker = GPUWorker(store, {JobKind.BROLL: processor}, job_timeout_s=60)
    worker.start()

    job = make_job("interrupted")
    await worker.submit(job)
    await wait_for_state(store, job.id, JobState.PROCESSING)

    await worker.stop()

    stopped = store.get(job.id)
    assert stopped is not None
    assert stopped.state is JobState.FAILED
    assert "shut down" in (stopped.error or "")


async def test_late_progress_after_terminal_state_is_ignored(store: JobStore) -> None:
    worker = GPUWorker(store, {JobKind.BROLL: FlakyProcessor()}, job_timeout_s=10)
    worker.start()
    try:
        job = make_job()
        await worker.submit(job)
        await wait_for_state(store, job.id, JobState.FINISHED)

        worker._apply_progress(job.id, 10, "stale")
        unchanged = store.get(job.id)
        assert unchanged is not None
        assert unchanged.progress == 100
        assert unchanged.state is JobState.FINISHED
    finally:
        await worker.stop()


async def test_failure_hook_called_on_crash(store: JobStore) -> None:
    seen: list[BaseException] = []

    async def hook(exc: BaseException) -> None:
        seen.append(exc)

    worker = GPUWorker(store, {JobKind.BROLL: FlakyProcessor()}, job_timeout_s=10, failure_hook=hook)
    worker.start()
    try:
        crashing = make_job("crash")
        healthy = make_job("healthy")
        await worker.submit(crashing)
        await worker.submit(healthy)
        await wait_for_state(store, healthy.id, JobState.FINISHED)

        assert len(seen) == 1  # crash yes, success no
        assert isinstance(seen[0], ValueError)
    finally:
        await worker.stop()


async def test_broken_failure_hook_does_not_kill_worker(store: JobStore) -> None:
    async def hook(exc: BaseException) -> None:
        raise RuntimeError("hook itself is broken")

    worker = GPUWorker(store, {JobKind.BROLL: FlakyProcessor()}, job_timeout_s=10, failure_hook=hook)
    worker.start()
    try:
        crashing = make_job("crash")
        healthy = make_job("healthy")
        await worker.submit(crashing)
        await worker.submit(healthy)

        await wait_for_state(store, crashing.id, JobState.FAILED)
        await wait_for_state(store, healthy.id, JobState.FINISHED)
    finally:
        await worker.stop()


# ---- persistence / rehydration ---------------------------------------------------


def test_snapshot_written_and_rehydrated(store: JobStore, tmp_path) -> None:
    job = make_job("persisted")
    store.add(job)
    store.update(job.id, state=JobState.FINISHED, outputs={"video": "/outputs/x/output.mp4"})

    snapshot_path = tmp_path / job.id / "status.json"
    assert snapshot_path.is_file()
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert data["state"] == "finished"

    fresh = JobStore(tmp_path)
    fresh.rehydrate()
    restored = fresh.get(job.id)
    assert restored is not None
    assert restored.state is JobState.FINISHED
    assert restored.outputs == {"video": "/outputs/x/output.mp4"}
    assert restored.params is None  # history entry, never reprocessed


def test_rehydrate_fails_interrupted_jobs(store: JobStore, tmp_path) -> None:
    queued = make_job("was-queued")
    processing = make_job("was-processing")
    store.add(queued)
    store.add(processing)
    store.update(processing.id, state=JobState.PROCESSING)

    fresh = JobStore(tmp_path)
    fresh.rehydrate()
    for job_id in (queued.id, processing.id):
        job = fresh.get(job_id)
        assert job is not None
        assert job.state is JobState.FAILED
        assert "restarted" in (job.error or "")
        assert job.finished_at is not None


def test_rehydrate_skips_corrupt_snapshot(tmp_path) -> None:
    good = make_job("good")
    store = JobStore(tmp_path)
    store.add(good)
    store.update(good.id, state=JobState.FINISHED, outputs={"video": "/v.mp4"})

    bad_dir = tmp_path / "corrupt-job"
    bad_dir.mkdir()
    (bad_dir / "status.json").write_text("{not valid json", encoding="utf-8")

    fresh = JobStore(tmp_path)
    fresh.rehydrate()
    assert fresh.get(good.id) is not None
    assert len(fresh.list_recent(limit=100)) == 1


def test_list_recent_orders_and_filters(store: JobStore) -> None:
    first = make_job("first")
    second = make_job("second", kind=JobKind.TALKING_HEAD)
    third = make_job("third")
    for job in (first, second, third):
        store.add(job)
    # force distinct creation order
    store.update(second.id, created_at=first.created_at.replace(microsecond=0))

    recent = store.list_recent(limit=2)
    assert len(recent) == 2

    broll_only = store.list_recent(limit=10, kind=JobKind.BROLL)
    assert {j.id for j in broll_only} == {first.id, third.id}


def test_update_rejects_unknown_field(store: JobStore) -> None:
    job = make_job()
    store.add(job)
    with pytest.raises(AttributeError):
        store.update(job.id, nonexistent_field=1)
