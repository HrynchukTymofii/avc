"""Job model: states, per-kind parameters, and the Job record itself.

The queue only ever carries job IDs; Job instances live in the JobStore, which is
the single source of truth for job state.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.schemas import JobKind


class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    FINISHED = "finished"
    FAILED = "failed"


TERMINAL_STATES = frozenset({JobState.FINISHED, JobState.FAILED})


@dataclass
class TalkingHeadParams:
    # avatar_path is None only for voice-only jobs (no video is rendered).
    avatar_path: Path | None
    script: str
    voice_id: str
    voice_only: bool = False
    # animate: synthesize a Wan idle-motion clip from the avatar first and
    # lip-sync onto it, instead of onto the frozen still. Derived from `model`
    # at the route (engine "musetalk-animate").
    animate: bool = False
    model: str = "musetalk"  # engine id from models_catalog


@dataclass
class BrollParams:
    prompt: str
    duration_s: int
    image_path: Path | None
    model: str = "wan-5b"  # engine id from models_catalog
    # Trained style adapter to apply (see services.loras); path resolved at submit.
    lora_id: str | None = None
    lora_path: Path | None = None
    lora_scale: float = 1.0


@dataclass
class ImageParams:
    prompt: str
    orientation: str  # key of wan_pipeline.IMAGE_SIZES
    model: str = "wan-5b"  # engine id from models_catalog
    count: int = 1  # variations per prompt (1-4), distinct seeds
    # Trained style adapter to apply (see services.loras); path resolved at submit.
    lora_id: str | None = None
    lora_path: Path | None = None
    lora_scale: float = 1.0
    # Reference-image editing (flux-kontext engine only): the uploaded image the
    # edit starts from, and how strongly the prompt pulls away from it.
    image_path: Path | None = None
    guidance: float = 2.5


@dataclass
class FullVideoParams:
    script: str  # tagged script (services.script_parser grammar)
    voice_id: str
    # avatar_path is None only when the script has no on-camera segments.
    avatar_path: Path | None
    orientation: str = "landscape"  # key of wan_pipeline.IMAGE_SIZES
    # casefolded [CLIP: …] name -> uploaded file saved under inputs/.
    clip_paths: dict[str, Path] = field(default_factory=dict)
    model: str = "full-video"  # engine id from models_catalog


@dataclass
class UpscaleParams:
    media_path: Path
    media: str  # "image" | "video"
    variant: str  # upscale_pipeline.VARIANTS key ("photo" | "anime")
    scale: int  # 2 | 4
    model: str = "realesrgan-photo"  # engine id from models_catalog


@dataclass
class LoraTrainingParams:
    # Style/character LoRA training on the Wan2.2 5B base (ostris/ai-toolkit).
    name: str  # display name for the finished style
    trigger: str  # trigger word baked into every caption
    dataset_dir: Path  # uploaded training images (captions written at run time)
    image_count: int
    description: str | None = None  # optional style hint appended to captions
    steps: int = 2000
    model: str = "wan22-5b-lora"  # engine id from models_catalog


JobParams = (
    TalkingHeadParams
    | BrollParams
    | ImageParams
    | FullVideoParams
    | LoraTrainingParams
    | UpscaleParams
)


def params_to_dict(params: JobParams) -> dict[str, Any]:
    """JSON-safe dict for the status.json snapshot (Paths become strings)."""

    def encode(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        return value

    return {key: encode(value) for key, value in asdict(params).items()}


def params_from_dict(kind: JobKind, data: dict[str, Any]) -> JobParams:
    """Inverse of params_to_dict. Raises on unknown kinds or missing fields —
    callers treat that as "no params" (snapshots from older versions)."""

    def path(value: Any) -> Path | None:
        return Path(value) if value else None

    if kind is JobKind.TALKING_HEAD:
        return TalkingHeadParams(
            avatar_path=path(data.get("avatar_path")),
            script=str(data["script"]),
            voice_id=str(data["voice_id"]),
            voice_only=bool(data.get("voice_only", False)),
            animate=bool(data.get("animate", False)),
            model=str(data.get("model", "musetalk")),
        )
    if kind is JobKind.BROLL:
        return BrollParams(
            prompt=str(data["prompt"]),
            duration_s=int(data["duration_s"]),
            image_path=path(data.get("image_path")),
            model=str(data.get("model", "wan-5b")),
            lora_id=data.get("lora_id") or None,
            lora_path=path(data.get("lora_path")),
            lora_scale=float(data.get("lora_scale", 1.0)),
        )
    if kind is JobKind.IMAGE:
        return ImageParams(
            prompt=str(data["prompt"]),
            orientation=str(data["orientation"]),
            model=str(data.get("model", "wan-5b")),
            count=int(data.get("count", 1)),
            lora_id=data.get("lora_id") or None,
            lora_path=path(data.get("lora_path")),
            lora_scale=float(data.get("lora_scale", 1.0)),
            image_path=path(data.get("image_path")),
            guidance=float(data.get("guidance", 2.5)),
        )
    if kind is JobKind.FULL_VIDEO:
        return FullVideoParams(
            script=str(data["script"]),
            voice_id=str(data["voice_id"]),
            avatar_path=path(data.get("avatar_path")),
            orientation=str(data.get("orientation", "landscape")),
            clip_paths={
                name: Path(clip) for name, clip in dict(data.get("clip_paths", {})).items()
            },
            model=str(data.get("model", "full-video")),
        )
    if kind is JobKind.UPSCALE:
        return UpscaleParams(
            media_path=Path(data["media_path"]),
            media=str(data["media"]),
            variant=str(data["variant"]),
            scale=int(data["scale"]),
            model=str(data.get("model", "realesrgan-photo")),
        )
    if kind is JobKind.LORA_TRAINING:
        return LoraTrainingParams(
            name=str(data["name"]),
            trigger=str(data["trigger"]),
            dataset_dir=Path(data["dataset_dir"]),
            image_count=int(data["image_count"]),
            description=data.get("description") or None,
            steps=int(data.get("steps", 2000)),
            model=str(data.get("model", "wan22-5b-lora")),
        )
    raise ValueError(f"unknown job kind {kind!r}")


def new_job_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    kind: JobKind
    # None only for jobs whose snapshot predates params persistence (or could
    # not be decoded) — those are history entries and cannot be regenerated.
    params: JobParams | None
    label: str = ""
    # Owner (AuthUser.id). "local" = the implicit user when auth is disabled,
    # and the owner of jobs created before accounts existed.
    user_id: str = "local"
    # Credits charged at submission (services.credits prices); 0 for jobs that
    # predate the credit system. Failed jobs are not counted as spend.
    cost: int = 0
    # Soft delete: hidden from listings and its output files removed, but the
    # record stays so credits_spent still counts what was charged.
    deleted: bool = False
    state: JobState = JobState.QUEUED
    progress: int = 0
    stage: str | None = None
    error: str | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
