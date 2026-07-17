"""GET /api/jobs/{id}, POST /api/jobs/{id}/regenerate and DELETE /api/jobs/{id}:
the library detail dialog and its actions."""

import logging
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings
from app.deps import get_loras, get_settings_dep, get_store, get_worker
from app.models_catalog import Engine, get_engine, is_available
from app.queue.job import (
    TERMINAL_STATES,
    BrollParams,
    FullVideoParams,
    ImageParams,
    Job,
    JobParams,
    JobState,
    LoraTrainingParams,
    TalkingHeadParams,
    UpscaleParams,
    new_job_id,
)
from app.queue.job_store import JobStore
from app.queue.worker import GPUWorker
from app.routes.voices import get_voices
from app.schemas import (
    ErrorResponse,
    JobCreatedResponse,
    JobDetailResponse,
    JobKind,
)
from app.services import credits
from app.services.auth import AuthUser, can_view, get_current_user
from app.services.credits import require_credits
from app.services.loras import LoraRegistry
from app.services.script_parser import parse_full_video_script
from app.services.voices import VoiceRegistry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])

_NOT_FOUND = {404: {"model": ErrorResponse}}


def _visible_job(job: Job | None, user: AuthUser) -> Job:
    # Someone else's (or a deleted) job reads as absent — don't leak existence.
    if job is None or job.deleted or not can_view(user, job.user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _input_paths(params: JobParams) -> list[Path]:
    """Files under the job's inputs/ dir that a rerun would need."""
    if isinstance(params, TalkingHeadParams):
        return [params.avatar_path] if params.avatar_path else []
    if isinstance(params, BrollParams):
        return [params.image_path] if params.image_path else []
    if isinstance(params, FullVideoParams):
        paths = list(params.clip_paths.values())
        if params.avatar_path:
            paths.append(params.avatar_path)
        return paths
    if isinstance(params, UpscaleParams):
        return [params.media_path]
    if isinstance(params, LoraTrainingParams):
        return [params.dataset_dir]
    return []


def _prompt_of(params: JobParams) -> str | None:
    if isinstance(params, (TalkingHeadParams, FullVideoParams)):
        return params.script
    if isinstance(params, (BrollParams, ImageParams)):
        return params.prompt
    if isinstance(params, LoraTrainingParams):
        return params.description
    return None


def _voice_of(params: JobParams) -> str | None:
    if isinstance(params, (TalkingHeadParams, FullVideoParams)):
        return params.voice_id
    return None


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


def _can_regenerate(job: Job) -> bool:
    return job.params is not None and all(p.exists() for p in _input_paths(job.params))


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetailResponse,
    response_model_exclude_none=True,
    responses=_NOT_FOUND,
)
async def get_job_detail(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> JobDetailResponse:
    job = _visible_job(store.get(job_id), user)
    return JobDetailResponse(
        job_id=job.id,
        kind=job.kind,
        status=job.state.value,
        label=job.label,
        created_at=job.created_at,
        cost=job.cost,
        model=getattr(job.params, "model", None),
        prompt=_prompt_of(job.params) if job.params else None,
        voice=_voice_of(job.params) if job.params else None,
        error=job.error,
        video=job.outputs.get("video"),
        audio=job.outputs.get("audio"),
        image=job.outputs.get("image"),
        images=_image_urls(job.outputs),
        can_regenerate=_can_regenerate(job),
        can_upscale=job.state is JobState.FINISHED
        and ("video" in job.outputs or "image" in job.outputs),
    )


def _cost_for(kind: JobKind, engine: Engine, params: JobParams) -> int:
    if isinstance(params, TalkingHeadParams):
        return credits.talking_head_cost(engine, params.script, params.voice_only)
    if isinstance(params, BrollParams):
        return credits.broll_cost(engine)
    if isinstance(params, ImageParams):
        return credits.image_cost(engine, params.count)
    if isinstance(params, FullVideoParams):
        segments = parse_full_video_script(params.script)
        return credits.full_video_cost(segments, params.script)
    if isinstance(params, UpscaleParams):
        return credits.upscale_cost(params.media)
    return credits.lora_training_cost()


def _remap_params(params: JobParams, old_inputs: Path, new_inputs: Path) -> JobParams:
    """Copy of `params` with every input path moved to the new job's inputs dir.
    Raises ValueError when a path isn't under the old inputs dir."""

    def move(path: Path | None) -> Path | None:
        if path is None:
            return None
        return new_inputs / path.relative_to(old_inputs)

    if isinstance(params, TalkingHeadParams):
        return replace(params, avatar_path=move(params.avatar_path))
    if isinstance(params, BrollParams):
        return replace(params, image_path=move(params.image_path))
    if isinstance(params, FullVideoParams):
        return replace(
            params,
            avatar_path=move(params.avatar_path),
            clip_paths={name: move(path) for name, path in params.clip_paths.items()},
        )
    if isinstance(params, UpscaleParams):
        return replace(params, media_path=move(params.media_path))
    if isinstance(params, LoraTrainingParams):
        return replace(params, dataset_dir=move(params.dataset_dir))
    return replace(params)


@router.post(
    "/jobs/{job_id}/regenerate",
    response_model=JobCreatedResponse,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse}},
)
async def regenerate_job(
    job_id: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    store: Annotated[JobStore, Depends(get_store)],
    voices: Annotated[VoiceRegistry, Depends(get_voices)],
    loras: Annotated[LoraRegistry, Depends(get_loras)],
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> JobCreatedResponse:
    """Re-submit a job with the same settings. Charged like a new job; the new
    job belongs to the caller."""
    source = _visible_job(store.get(job_id), user)
    params = source.params
    if params is None:
        raise HTTPException(
            status_code=409,
            detail="This job's settings weren't saved, so it can't be regenerated.",
        )
    if any(not p.exists() for p in _input_paths(params)):
        raise HTTPException(
            status_code=409,
            detail="This job's input files are no longer on the server.",
        )
    engine = get_engine(source.kind, params.model)
    if engine is None or not is_available(engine, settings):
        raise HTTPException(
            status_code=409,
            detail=f"Model {params.model!r} is not available on this server anymore.",
        )
    if _voice_of(params) is not None and voices.get(params.voice_id) is None:
        raise HTTPException(
            status_code=409,
            detail=f"Voice {params.voice_id!r} no longer exists on the server.",
        )
    # Styles may have been retrained or deleted since — resolve them fresh.
    lora_path = None
    if isinstance(params, (BrollParams, ImageParams)) and params.lora_id:
        style = loras.get(params.lora_id)
        if style is None:
            raise HTTPException(
                status_code=409,
                detail="The style this job used has been deleted.",
            )
        lora_path = style.weights_path

    cost = _cost_for(source.kind, engine, params)
    require_credits(user, cost, store)

    new_id = new_job_id()
    old_inputs = settings.outputs_dir / source.id / "inputs"
    new_inputs = settings.outputs_dir / new_id / "inputs"
    try:
        new_params = _remap_params(params, old_inputs, new_inputs)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="This job's input files are no longer on the server.",
        ) from None
    if lora_path is not None:
        new_params = replace(new_params, lora_path=lora_path)
    if old_inputs.is_dir():
        shutil.copytree(old_inputs, new_inputs)

    job = Job(
        id=new_id,
        kind=source.kind,
        params=new_params,
        label=source.label,
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    log.info("job regenerated", extra={"source": source.id, "job": new_id})
    return JobCreatedResponse(job_id=new_id)


@router.delete(
    "/jobs/{job_id}",
    status_code=204,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse}},
)
async def delete_job(
    job_id: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> None:
    """Soft-delete: the job disappears from listings and its files are removed,
    but the record stays so spent credits stay spent."""
    job = _visible_job(store.get(job_id), user)
    if job.state not in TERMINAL_STATES:
        raise HTTPException(
            status_code=409,
            detail="This job is still running — wait for it to finish first.",
        )
    store.update(job.id, deleted=True, outputs={})
    job_dir = settings.outputs_dir / job.id
    if job_dir.is_dir():
        for entry in job_dir.iterdir():
            if entry.name == "status.json":
                continue  # the snapshot IS the spend record — keep it
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                log.warning("could not remove %s", entry)
