"""GET /api/status/{job_id} and GET /api/jobs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_settings_dep, get_store
from app.config import Settings
from app.queue.job import Job, JobState
from app.queue.job_store import JobStore
from app.schemas import (
    ErrorResponse,
    FailedStatus,
    FinishedStatus,
    JobKind,
    JobListResponse,
    JobSummary,
    ProcessingStatus,
    QueuedStatus,
    StatusResponse,
)

router = APIRouter(prefix="/api", tags=["status"])


def _status_for(job: Job, store: JobStore) -> StatusResponse:
    if job.state is JobState.QUEUED:
        return QueuedStatus(position=store.queued_position(job.id) or 1)
    if job.state is JobState.PROCESSING:
        return ProcessingStatus(
            progress=job.progress,
            stage=job.stage or "starting",
            audio=job.outputs.get("audio"),
        )
    if job.state is JobState.FINISHED:
        return FinishedStatus(
            video=job.outputs.get("video"),
            audio=job.outputs.get("audio"),
            image=job.outputs.get("image"),
        )
    return FailedStatus(error=job.error or "Unknown error")


@router.get(
    "/status/{job_id}",
    response_model=StatusResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorResponse}},
)
async def get_status(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
) -> StatusResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _status_for(job, store)


@router.get("/jobs", response_model=JobListResponse, response_model_exclude_none=True)
async def list_jobs(
    store: Annotated[JobStore, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    kind: Annotated[JobKind | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> JobListResponse:
    jobs = store.list_recent(limit=limit or settings.recent_jobs_limit, kind=kind)
    return JobListResponse(
        jobs=[
            JobSummary(
                job_id=job.id,
                kind=job.kind,
                status=job.state.value,
                label=job.label,
                created_at=job.created_at,
                video=job.outputs.get("video"),
                audio=job.outputs.get("audio"),
                image=job.outputs.get("image"),
            )
            for job in jobs
        ]
    )
