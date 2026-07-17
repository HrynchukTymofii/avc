"""GET /api/status/{job_id}, GET /api/jobs and GET /api/credits."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_settings_dep, get_store
from app.config import Settings
from app.queue.job import Job, JobState
from app.queue.job_store import JobStore
from app.services.auth import AuthUser, can_view, get_current_user
from app.schemas import (
    CreditsResponse,
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


def _image_urls(outputs: dict[str, str]) -> list[str] | None:
    """Reassemble the image list from the flat outputs keys (image, image_2…)."""
    if "image" not in outputs:
        return None
    urls = [outputs["image"]]
    position = 2
    while f"image_{position}" in outputs:
        urls.append(outputs[f"image_{position}"])
        position += 1
    return urls


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
            images=_image_urls(job.outputs),
            lora=job.outputs.get("lora"),
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
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> StatusResponse:
    job = store.get(job_id)
    # Someone else's (or a deleted) job reads as absent — don't leak existence.
    if job is None or job.deleted or not can_view(user, job.user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return _status_for(job, store)


@router.get("/credits", response_model=CreditsResponse)
async def get_credits(
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> CreditsResponse:
    if user.role == "admin":
        return CreditsResponse(allowance=0, spent=0, balance=0, unlimited=True)
    spent = store.credits_spent(user.id)
    return CreditsResponse(
        allowance=user.credits,
        spent=spent,
        balance=max(user.credits - spent, 0),
    )


@router.get("/jobs", response_model=JobListResponse, response_model_exclude_none=True)
async def list_jobs(
    store: Annotated[JobStore, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    kind: Annotated[JobKind | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> JobListResponse:
    jobs = store.list_recent(
        limit=limit or settings.recent_jobs_limit,
        kind=kind,
        # Admins see the whole queue; everyone else sees their own history.
        user_id=None if user.role == "admin" else user.id,
    )
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
