"""In-memory job registry with per-job status.json snapshots on disk.

All reads and writes happen on the event loop, so no locking is needed. Every
state change is snapshotted to outputs/{jobId}/status.json (atomically, via
write-to-temp-then-rename); progress-only updates are throttled so diffusion
step callbacks don't hammer the disk. On startup, rehydrate() reloads history
so /api/jobs survives restarts — jobs that were queued or processing when the
process died are rewritten as failed.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.queue.job import Job, JobState, utc_now
from app.schemas import JobKind

log = logging.getLogger(__name__)

_PROGRESS_PERSIST_INTERVAL_S = 1.0
_SNAPSHOT_NAME = "status.json"


class JobStore:
    def __init__(self, outputs_dir: Path) -> None:
        self._outputs_dir = outputs_dir
        self._jobs: dict[str, Job] = {}
        self._last_persist: dict[str, float] = {}

    def add(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._persist(job)
        self._last_persist[job.id] = time.monotonic()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_recent(
        self,
        limit: int = 20,
        kind: JobKind | None = None,
        user_id: str | None = None,
    ) -> list[Job]:
        jobs = self._jobs.values()
        if kind is not None:
            jobs = (j for j in jobs if j.kind is kind)
        if user_id is not None:
            jobs = (j for j in jobs if j.user_id == user_id)
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def queued_position(self, job_id: str) -> int | None:
        """1-based index among QUEUED jobs ordered by creation time; None if the
        job is not queued. Computed at read time so positions are always
        self-consistent — when the worker takes a job, everyone moves up."""
        queued = sorted(
            (j for j in self._jobs.values() if j.state is JobState.QUEUED),
            key=lambda j: j.created_at,
        )
        for index, job in enumerate(queued, start=1):
            if job.id == job_id:
                return index
        return None

    def update(self, job_id: str, **changes: Any) -> Job:
        job = self._jobs[job_id]
        for key, value in changes.items():
            if not hasattr(job, key):
                raise AttributeError(f"Job has no field {key!r}")
            setattr(job, key, value)

        progress_only = set(changes) <= {"progress", "stage"}
        now = time.monotonic()
        if (
            not progress_only
            or now - self._last_persist.get(job_id, 0.0) >= _PROGRESS_PERSIST_INTERVAL_S
        ):
            self._persist(job)
            self._last_persist[job_id] = now
        return job

    def rehydrate(self) -> None:
        total = interrupted = 0
        for snapshot_path in sorted(self._outputs_dir.glob(f"*/{_SNAPSHOT_NAME}")):
            try:
                data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                job = _job_from_snapshot(data)
            except Exception:
                log.warning(
                    "skipping unreadable job snapshot", extra={"path": str(snapshot_path)}
                )
                continue
            if job.state not in (JobState.FINISHED, JobState.FAILED):
                job.state = JobState.FAILED
                job.error = "Server restarted while this job was in progress"
                job.finished_at = job.finished_at or utc_now()
                self._persist(job)
                interrupted += 1
            self._jobs[job.id] = job
            total += 1
        log.info("job store rehydrated", extra={"jobs": total, "interrupted": interrupted})

    def _persist(self, job: Job) -> None:
        job_dir = self._outputs_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        snapshot = json.dumps(_snapshot_from_job(job), ensure_ascii=False, indent=2)
        tmp_path = job_dir / f"{_SNAPSHOT_NAME}.tmp"
        tmp_path.write_text(snapshot, encoding="utf-8")
        tmp_path.replace(job_dir / _SNAPSHOT_NAME)


def _snapshot_from_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind.value,
        "state": job.state.value,
        "label": job.label,
        "user_id": job.user_id,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "outputs": job.outputs,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _job_from_snapshot(data: dict[str, Any]) -> Job:
    def parse_dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    created_at = parse_dt(data.get("created_at"))
    if created_at is None:
        raise ValueError("snapshot missing created_at")
    return Job(
        id=str(data["id"]),
        kind=JobKind(data["kind"]),
        params=None,
        label=str(data.get("label", "")),
        user_id=str(data.get("user_id", "local")),
        state=JobState(data["state"]),
        progress=int(data.get("progress", 0)),
        stage=data.get("stage"),
        error=data.get("error"),
        outputs=dict(data.get("outputs", {})),
        created_at=created_at,
        started_at=parse_dt(data.get("started_at")),
        finished_at=parse_dt(data.get("finished_at")),
    )
