"""POST /api/talking-head, /api/broll, /api/image and /api/full-video:
validate, save inputs, enqueue."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import Settings
from app.deps import get_loras, get_settings_dep, get_store, get_worker
from app.models_catalog import Engine, get_engine, is_available
from app.pipelines.wan_pipeline import IMAGE_SIZES
from app.pipelines.upscale_pipeline import OUTPUT_SCALES
from app.queue.job import (
    BrollParams,
    FullVideoParams,
    ImageParams,
    Job,
    JobState,
    LoraTrainingParams,
    TalkingHeadParams,
    UpscaleParams,
    new_job_id,
)
from app.queue.job_store import JobStore
from app.queue.worker import GPUWorker
from app.routes.voices import get_voices
from app.schemas import ErrorResponse, JobCreatedResponse, JobKind
from app.services import credits, ffmpeg
from app.services.auth import AuthUser, can_view, get_current_user
from app.services.credits import require_credits
from app.services.loras import TRIGGER_RE, LoraRegistry, LoraStyleInfo
from app.services.script_parser import SegmentKind, parse_full_video_script
from app.services.validation import (
    InputValidationError,
    read_image_upload,
    read_media_upload,
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


def _resolve_lora(
    lora: str, engine: Engine, registry: LoraRegistry
) -> LoraStyleInfo | None:
    """Validate a requested style adapter against the registry and the engine.
    Styles are trained on (and only apply to) the Wan2.2 5B family."""
    if not lora:
        return None
    info = registry.get(lora)
    if info is None:
        raise InputValidationError(
            f"unknown style {lora!r} — see /api/loras for trained styles"
        )
    if engine.id != "wan-5b":
        raise InputValidationError(
            f"style {info.name!r} was trained for the Wan2.2 5B engine — "
            f"it cannot be applied to model {engine.id!r}"
        )
    return info


def _prompt_with_trigger(prompt: str, style: LoraStyleInfo | None) -> str:
    """The trigger word must appear in the prompt for the adapter to fire;
    prepend it when the user leaves it out."""
    if style is None or style.trigger.lower() in prompt.lower():
        return prompt
    return f"{style.trigger}, {prompt}"


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
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
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
    cost = credits.talking_head_cost(engine, script, voice_only)
    require_credits(user, cost, store)

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
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


@router.post("/broll", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_broll(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    loras: Annotated[LoraRegistry, Depends(get_loras)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    prompt: Annotated[str, Form()],
    duration: Annotated[int, Form(ge=3, le=5)],
    image: Annotated[UploadFile | None, File()] = None,
    model: Annotated[str, Form()] = "wan-5b",
    lora: Annotated[str, Form()] = "",
    lora_scale: Annotated[float, Form(ge=0.1, le=2.0)] = 1.0,
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.BROLL, model, settings)
    prompt = validate_text(prompt, field="prompt", max_chars=settings.max_prompt_chars)
    style = _resolve_lora(lora, engine, loras)
    prompt = _prompt_with_trigger(prompt, style)
    cost = credits.broll_cost(engine)
    require_credits(user, cost, store)

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
            prompt=prompt,
            duration_s=duration,
            image_path=image_path,
            model=engine.id,
            lora_id=style.id if style else None,
            lora_path=style.weights_path if style else None,
            lora_scale=lora_scale,
        ),
        label=_label(prompt),
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


@router.post("/image", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_image(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    loras: Annotated[LoraRegistry, Depends(get_loras)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    prompt: Annotated[str, Form()],
    orientation: Annotated[str, Form()] = "landscape",
    model: Annotated[str, Form()] = "wan-5b",
    count: Annotated[int, Form(ge=1, le=4)] = 1,
    lora: Annotated[str, Form()] = "",
    lora_scale: Annotated[float, Form(ge=0.1, le=2.0)] = 1.0,
    image: Annotated[UploadFile | None, File()] = None,
    guidance: Annotated[float, Form(ge=1.0, le=5.0)] = 2.5,
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.IMAGE, model, settings)
    prompt = validate_text(prompt, field="prompt", max_chars=settings.max_prompt_chars)
    style = _resolve_lora(lora, engine, loras)
    prompt = _prompt_with_trigger(prompt, style)
    if orientation not in IMAGE_SIZES:
        raise InputValidationError(
            f"orientation must be one of {', '.join(sorted(IMAGE_SIZES))}"
        )
    has_reference = image is not None and bool(image.filename or image.size)
    if engine.id == "flux-kontext" and not has_reference:
        raise InputValidationError(
            "the Kontext engine edits an existing image — upload a reference image"
        )
    if has_reference and engine.id != "flux-kontext":
        raise InputValidationError(
            "reference images are only supported by the FLUX.1 Kontext engine"
        )
    cost = credits.image_cost(engine, count)
    require_credits(user, cost, store)

    job_id = new_job_id()
    image_path = None
    if has_reference:
        assert image is not None
        image_bytes, extension = await read_image_upload(
            image, max_bytes=settings.max_upload_bytes, field="image"
        )
        image_path = settings.outputs_dir / job_id / "inputs" / f"reference{extension}"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)

    job = Job(
        id=job_id,
        kind=JobKind.IMAGE,
        params=ImageParams(
            prompt=prompt,
            orientation=orientation,
            model=engine.id,
            count=count,
            lora_id=style.id if style else None,
            lora_path=style.weights_path if style else None,
            lora_scale=lora_scale,
            image_path=image_path,
            guidance=guidance,
        ),
        label=_label(prompt),
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job.id)


@router.post("/full-video", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_full_video(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    voices: Annotated[VoiceRegistry, Depends(get_voices)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
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
    cost = credits.full_video_cost(segments, script)
    require_credits(user, cost, store)

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
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


_UPSCALE_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
_UPSCALE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _read_source_job_output(
    source_job: str,
    source: str,
    store: JobStore,
    settings: Settings,
    user: AuthUser,
) -> tuple[bytes, str, str, str]:
    """Resolve an upscale source from a finished job's output instead of an
    upload. Returns (bytes, extension, media, display name)."""
    job = store.get(source_job)
    if job is None or job.deleted or not can_view(user, job.user_id):
        raise HTTPException(status_code=404, detail="Source job not found")
    if job.state is not JobState.FINISHED:
        raise InputValidationError("the source job has no finished output yet")
    key = source or ("video" if "video" in job.outputs else "image")
    url = job.outputs.get(key)
    if not url:
        raise InputValidationError(f"the source job has no {key!r} output")
    # Outputs are always "/outputs/{jobId}/{name}" — resolve by basename so a
    # crafted key can't escape the job's own directory.
    path = settings.outputs_dir / job.id / Path(url).name
    if not path.is_file():
        raise InputValidationError("the source file is no longer on the server")
    extension = path.suffix.lower()
    if extension in _UPSCALE_VIDEO_EXTS:
        media = "video"
    elif extension in _UPSCALE_IMAGE_EXTS:
        media = "image"
    else:
        raise InputValidationError("only video and image outputs can be upscaled")
    return path.read_bytes(), extension, media, job.label or Path(url).name


@router.post("/upscale", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_upscale(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    file: Annotated[UploadFile | None, File()] = None,
    # Alternative to `file`: upscale a finished job's output straight from the
    # server (no re-upload). `source` picks the outputs key for multi-image jobs.
    source_job: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "realesrgan-photo",
    scale: Annotated[int, Form()] = 4,
) -> JobCreatedResponse:
    engine = _resolve_engine(JobKind.UPSCALE, model, settings)
    if scale not in OUTPUT_SCALES:
        raise InputValidationError(
            f"scale must be one of {', '.join(str(s) for s in OUTPUT_SCALES)}"
        )

    if source_job:
        data, extension, media, source_name = _read_source_job_output(
            source_job, source, store, settings, user
        )
    elif file is not None and (file.filename or file.size):
        data, extension, media = await read_media_upload(
            file,
            max_image_bytes=settings.max_upload_bytes,
            max_video_bytes=settings.max_clip_upload_bytes,
            field="file",
        )
        source_name = Path(file.filename or "").name or f"{media} upload"
    else:
        raise InputValidationError("upload a file or pass source_job")
    cost = credits.upscale_cost(media)
    require_credits(user, cost, store)

    if media == "image":
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            megapixels = (image.width * image.height) / 1_000_000
        if megapixels > settings.upscale_max_image_mp:
            raise InputValidationError(
                f"image is {megapixels:.1f} MP — the maximum is "
                f"{settings.upscale_max_image_mp:g} MP (it would be huge after 4x)"
            )

    job_id = new_job_id()
    media_path = settings.outputs_dir / job_id / "inputs" / f"source{extension}"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(data)

    if media == "video":
        try:
            duration = await ffmpeg.probe_duration(media_path)
        except ffmpeg.FFmpegError as exc:
            raise InputValidationError("file is not a playable video") from exc
        if duration > settings.upscale_max_video_s:
            raise InputValidationError(
                f"video is {duration:.0f} s — the maximum is "
                f"{settings.upscale_max_video_s:.0f} s"
            )

    job = Job(
        id=job_id,
        kind=JobKind.UPSCALE,
        params=UpscaleParams(
            media_path=media_path,
            media=media,
            variant="anime" if engine.id == "realesrgan-anime" else "photo",
            scale=scale,
            model=engine.id,
        ),
        label=_label(f"{source_name} · {scale}x"),
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)


@router.post("/lora-training", response_model=JobCreatedResponse, responses=_RESPONSES)
async def create_lora_training(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    worker: Annotated[GPUWorker, Depends(get_worker)],
    store: Annotated[JobStore, Depends(get_store)],
    user: Annotated[AuthUser, Depends(get_current_user)],
    name: Annotated[str, Form()],
    trigger: Annotated[str, Form()],
    images: Annotated[list[UploadFile], File()],
    description: Annotated[str, Form()] = "",
    steps: Annotated[int, Form(ge=0)] = 0,
    model: Annotated[str, Form()] = "wan22-5b-lora",
) -> JobCreatedResponse:
    _resolve_engine(JobKind.LORA_TRAINING, model, settings)
    cost = credits.lora_training_cost()
    require_credits(user, cost, store)
    name = validate_text(name, field="name", max_chars=60)
    trigger = trigger.strip()
    if not TRIGGER_RE.match(trigger):
        raise InputValidationError(
            "trigger must be a single made-up word: 2-30 letters, digits or "
            "underscores (e.g. 'zork_style')"
        )
    description = description.strip()
    if description:
        description = validate_text(
            description, field="description", max_chars=settings.max_prompt_chars
        )
    steps = steps or settings.lora_default_steps
    if steps > settings.lora_max_steps:
        raise InputValidationError(
            f"steps must be at most {settings.lora_max_steps}"
        )

    uploads = [u for u in images if u.filename or u.size]
    if len(uploads) < settings.lora_min_images:
        raise InputValidationError(
            f"at least {settings.lora_min_images} training images are required "
            f"(got {len(uploads)}) — 20-50 varied images of the character/style "
            "work best"
        )
    if len(uploads) > settings.lora_max_images:
        raise InputValidationError(
            f"at most {settings.lora_max_images} training images are allowed "
            f"(got {len(uploads)})"
        )

    job_id = new_job_id()
    dataset_dir = settings.outputs_dir / job_id / "inputs" / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for index, upload in enumerate(uploads):
        image_bytes, extension = await read_image_upload(
            upload,
            max_bytes=settings.max_upload_bytes,
            field=f"image {upload.filename or index + 1!r}",
        )
        (dataset_dir / f"img_{index:03d}{extension}").write_bytes(image_bytes)

    job = Job(
        id=job_id,
        kind=JobKind.LORA_TRAINING,
        params=LoraTrainingParams(
            name=name,
            trigger=trigger,
            dataset_dir=dataset_dir,
            image_count=len(uploads),
            description=description or None,
            steps=steps,
        ),
        label=f"{name} · {len(uploads)} images",
        user_id=user.id,
        cost=cost,
    )
    await worker.submit(job)
    return JobCreatedResponse(job_id=job_id)
