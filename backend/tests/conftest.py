import asyncio
from pathlib import Path

import pytest

from app.queue.job import BrollParams, Job, JobState, new_job_id
from app.queue.job_store import JobStore
from app.schemas import JobKind


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path)


def make_job(label: str = "", kind: JobKind = JobKind.BROLL) -> Job:
    return Job(
        id=new_job_id(),
        kind=kind,
        params=BrollParams(prompt="a test prompt", duration_s=3, image_path=None),
        label=label or "a test prompt",
    )


async def wait_for_state(
    store: JobStore, job_id: str, *states: JobState, timeout: float = 5.0
) -> Job:
    async def poll() -> Job:
        while True:
            job = store.get(job_id)
            assert job is not None
            if job.state in states:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=timeout)
