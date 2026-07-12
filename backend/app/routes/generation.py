"""POST /api/talking-head, /api/broll, /api/image and /api/full-video:
validate, save inputs, enqueue."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.config import Settings
from app.deps import get_settings_dep, get_worker
from app.models_catalog import Engine, get_engine, is_available
from app.pipelines.wan_pipeline import IMAGE_SIZES
from app.queue.job import (
    BrollParams,
    FullVideoParams,
    ImageParams,
    Job,
    TalkingHeadParams,
    new_job_id,
)
from app.queue.worker import GPUWorker
from app.routes.voices import get_voices
from app.schemas import ErrorResponse, JobCreatedResponse, JobKind
from app.services import ffmpeg
from app.services.script_parser import SegmentKind, parse_full_video_script
from app.services.validation import (
    InputValidationError,
    read_image_upload,
    read_video_upload,
    validate_text,
)
from app.services.voices import VoiceRegistry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generation"])

_RESPONSES = {422: {"model": ErrorResponse}}


def _label(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit].rstrip() + ("…" if len(collapsed) > limit else "")


def _resolve_engine(kind: JobKind, model: str, settings: Settings) -> Engine:
    engine = get_engine(kind, model)
    if engine is None:
        raise InputValidationError(
            f"unknown model {model!r} for {kind.value} — see /api/models"
        )
    if not is_available(engine, settings):
        raise InputValidationError(
            f"model {model!r} is not available yet — it requires the premium GPU tier"
        )
    return engine


@router.post("/talking-head", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_talking_head(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    voices: Annotated[VoiceRegistry, Depends(get_voices)],
    script: Annotated[str, Form()],
    voice: Annotated[str, Form()],
    avatar: Annotated[UploadFile | None, File()] = None,
    voice_only: Annotated[bool, Form()] = False,
    model: Annotated[str, Form()] = "musetalk",
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.TALKING_HEAD, model, settings)
    script = validate_text(script, field="script", max_chars=settings.max_script_chars)
    if voices.get(voice) is None:
        raise InputValidationError(
            f"unknown voice {voice!r} — see /api/voices for available voices"
        )

    job_id = new_job_id()
    avatar_path = None
    if not voice_only:
        if avatar is None or not (avatar.filename or avatar.size):
            raise InputValidationError(
                "avatar image is required unless voice_only is set"
            )
        image_bytes, extension = await read_image_upload(
            avatar, max_bytes=settings.max_upload_bytes, field="avatar"
        )
        avatar_path = settings.outputs_dir / job_id / "inputs" / f"avatar{extension}"
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar_path.write_bytes(image_bytes)

    job = Job(
        id=job_id,
        kind=JobKind.TALKING_HEAD,
        params=TalkingHeadParams(
            avatar_path=avatar_path,
            script=script,
            voice_id=voice,
            voice_only=voice_only,
            animate=engine.id == "musetalk-animate" and not voice_only,
            model=engine.id,
        ),
        label=_label(script),
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


@router.post("/broll", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_broll(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    prompt: Annotated[str, Form()],
    duration: Annotated[int, Form(ge=3, le=5)],
    image: Annotated[UploadFile | None, File()] = None,
    model: Annotated[str, Form()] = "wan-5b",
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.BROLL, model, settings)
    prompt = validate_text(prompt, field="prompt", max_chars=settings.max_prompt_chars)

    job_id = new_job_id()
    image_path = None
    if image is not None and (image.filename or image.size):
        image_bytes, extension = await read_image_upload(
            image, max_bytes=settings.max_upload_bytes, field="image"
        )
        image_path = settings.outputs_dir / job_id / "inputs" / f"reference{extension}"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)

    job = Job(
        id=job_id,
        kind=JobKind.BROLL,
        params=BrollParams(
            prompt=prompt, duration_s=duration, image_path=image_path, model=engine.id
        ),
        label=_label(prompt),
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


@router.post("/image", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_image(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    prompt: Annotated[str, Form()],
    orientation: Annotated[str, Form()] = "landscape",
    model: Annotated[str, Form()] = "wan-5b",
    count: Annotated[int, Form(ge=1, le=4)] = 1,
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.IMAGE, model, settings)
    prompt = validate_text(prompt, field="prompt", max_chars=settings.max_prompt_chars)
    if orientation not in IMAGE_SIZES:
        raise InputValidationError(
            f"orientation must be one of {', '.join(sorted(IMAGE_SIZES))}"
        )

    job = Job(
        id=new_job_id(),
        kind=JobKind.IMAGE,
        params=ImageParams(
            prompt=prompt, orientation=orientation, model=engine.id, count=count
        ),
        label=_label(prompt),
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job.id)


@router.post("/full-video", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_full_video(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    voices: Annotated[VoiceRegistry, Depends(get_voices)],
    script: Annotated[str, Form()],
    voice: Annotated[str, Form()],
    avatar: Annotated[UploadFile | None, File()] = None,
    orientation: Annotated[str, Form()] = "landscape",
    clips: Annotated[list[UploadFile] | None, File()] = None,
    model: Annotated[str, Form()] = "full-video",
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.FULL_VIDEO, model, settings)
    script = validate_text(script, field="script", max_chars=settings.max_script_chars)
    if orientation not in IMAGE_SIZES:
        raise InputValidationError(
            f"orientation must be one of {', '.join(sorted(IMAGE_SIZES))}"
        )
    if voices.get(voice) is None:
        raise InputValidationError(
            f"unknown voice {voice!r} — see /api/voices for available voices"
        )

    segments = parse_full_video_script(script)
    if len(segments) > settings.full_video_max_segments:
        raise InputValidationError(
            f"script has {len(segments)} segments — "
            f"the maximum is {settings.full_video_max_segments}"
        )

    # Match [CLIP: …] references against the uploaded files by (casefolded)
    # basename before touching the disk.
    referenced = {
        s.clip_name.casefold(): s.clip_name
        for s in segments
        if s.kind is SegmentKind.CLIP and s.clip_name
    }
    uploads: dict[str, UploadFile] = {}
    for upload in clips or []:
        if not (upload.filename or upload.size):
            continue  # empty multipart placeholder
        name = Path(upload.filename or "").name.casefold()
        if name in uploads:
            raise InputValidationError(f"duplicate clip upload {name!r}")
        uploads[name] = upload
    missing = sorted(referenced.keys() - uploads.keys())
    if missing:
        raise InputValidationError(
            "the script references clips that were not uploaded: " + ", ".join(missing)
        )
    for name in uploads.keys() - referenced.keys():
        log.info("ignoring uploaded clip not referenced by the script", extra={"clip": name})

    has_oncamera = any(s.kind is SegmentKind.ONCAMERA for s in segments)
    job_id = new_job_id()
    inputs_dir = settings.outputs_dir / job_id / "inputs"

    avatar_path = None
    if has_oncamera:
        if avatar is None or not (avatar.filename or avatar.size):
            raise InputValidationError(
                "avatar image is required — the script has on-camera segments"
            )
        image_bytes, extension = await read_image_upload(
            avatar, max_bytes=settings.max_upload_bytes, field="avatar"
        )
        avatar_path = inputs_dir / f"avatar{extension}"
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar_path.write_bytes(image_bytes)

    clip_paths: dict[str, Path] = {}
    for index, name in enumerate(sorted(referenced)):
        video_bytes, extension = await read_video_upload(
            uploads[name], max_bytes=settings.max_clip_upload_bytes, field=f"clip {name!r}"
        )
        clip_path = inputs_dir / f"clip_{index}{extension}"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(video_bytes)
        try:
            await ffmpeg.probe_duration(clip_path)
        except ffmpeg.FFmpegError as exc:
            raise InputValidationError(
                f"clip {referenced[name]!r} is not a playable video"
            ) from exc
        clip_paths[name] = clip_path

    job = Job(
        id=job_id,
        kind=JobKind.FULL_VIDEO,
        params=FullVideoParams(
            script=script,
            voice_id=voice,
            avatar_path=avatar_path,
            orientation=orientation,
            clip_paths=clip_paths,
            model=engine.id,
        ),
        label=_label(script),
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)
