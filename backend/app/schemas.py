"""Pydantic models for every API request and response (see ARCHITECTURE.md section 4)."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- shared ------------------------------------------------------------------


class JobKind(str, Enum):
    TALKING_HEAD = "talking_head"
    BROLL = "broll"
    IMAGE = "image"
    FULL_VIDEO = "full_video"
    LORA_TRAINING = "lora_training"
    UPSCALE = "upscale"


class JobCreatedResponse(BaseModel):
    job_id: str = Field(serialization_alias="jobId")


class ErrorResponse(BaseModel):
    detail: str


class CreditsResponse(BaseModel):
    # allowance = User.credits from the account DB; spent = non-failed job
    # costs; balance = what's left to spend. Admins report unlimited=True.
    allowance: int
    spent: int
    balance: int
    unlimited: bool = False


# ---- request text fields (from multipart forms) --------------------------------
# Length limits come from Settings and are enforced in services.validation, so the
# models here only pin the shape and the fixed product constraints.


class TalkingHeadRequest(BaseModel):
    script: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class BrollRequest(BaseModel):
    prompt: str = Field(min_length=1)
    duration: int = Field(ge=3, le=5)


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    orientation: Literal["landscape", "portrait", "square"] = "landscape"


class FullVideoRequest(BaseModel):
    # The script carries inline visual markers ([BROLL: …], [IMAGE: …],
    # [CLIP: …], [ONCAMERA]) parsed by services.script_parser.
    script: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    orientation: Literal["landscape", "portrait", "square"] = "landscape"


# ---- status: discriminated union on `status` ------------------------------------


class QueuedStatus(BaseModel):
    status: Literal["queued"] = "queued"
    position: int = Field(ge=1)


class ProcessingStatus(BaseModel):
    # `audio` appears mid-job once the voice track exists (talking-head jobs
    # publish it after the TTS stage so the UI can offer it during lip-sync).
    status: Literal["processing"] = "processing"
    progress: int = Field(ge=0, le=100)
    stage: str
    audio: str | None = None


class FinishedStatus(BaseModel):
    # `audio` is talking-head only; `video` is absent for voice-only jobs;
    # `image` is image jobs only; `lora` is the trained style id for
    # lora-training jobs.
    # Routes serialize with exclude_none so absent keys are omitted, not null.
    status: Literal["finished"] = "finished"
    video: str | None = None
    audio: str | None = None
    image: str | None = None
    # All generated images for multi-image jobs (image holds the first one).
    images: list[str] | None = None
    lora: str | None = None


class FailedStatus(BaseModel):
    status: Literal["failed"] = "failed"
    error: str


StatusResponse = Annotated[
    QueuedStatus | ProcessingStatus | FinishedStatus | FailedStatus,
    Field(discriminator="status"),
]


# ---- job list --------------------------------------------------------------------


class JobSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(serialization_alias="jobId")
    kind: JobKind
    status: Literal["queued", "processing", "finished", "failed"]
    label: str
    created_at: datetime = Field(serialization_alias="createdAt")
    video: str | None = None
    audio: str | None = None
    image: str | None = None
    # All generated images for multi-image jobs (image holds the first one) —
    # the grids render one tile per image.
    images: list[str] | None = None
    # talking_head only: True for narration-only jobs (the Voice Over tab shows
    # exactly these; the Talking Head tab hides them). None when unknown.
    voice_only: bool | None = Field(default=None, serialization_alias="voiceOnly")
    # upscale only: which media type the job enlarges (the Upscale Image and
    # Upscale Video views filter on this). None when unknown.
    media: Literal["image", "video"] | None = None


class JobListResponse(BaseModel):
    jobs: list[JobSummary]


class JobDetailResponse(BaseModel):
    """Everything the library detail dialog shows about one job."""

    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(serialization_alias="jobId")
    kind: JobKind
    status: Literal["queued", "processing", "finished", "failed"]
    label: str
    created_at: datetime = Field(serialization_alias="createdAt")
    cost: int
    # Engine id and the prompt/script the job was created with (absent when the
    # snapshot predates params persistence).
    model: str | None = None
    prompt: str | None = None
    voice: str | None = None
    error: str | None = None
    video: str | None = None
    audio: str | None = None
    image: str | None = None
    images: list[str] | None = None
    # False when the job's settings weren't saved (pre-update history) or its
    # input files are gone — the UI greys the Regenerate button out.
    can_regenerate: bool = Field(default=False, serialization_alias="canRegenerate")
    # True for finished jobs with a video or image output.
    can_upscale: bool = Field(default=False, serialization_alias="canUpscale")


# ---- voices ------------------------------------------------------------------------


class Voice(BaseModel):
    id: str
    name: str
    language: str
    ref_audio: Path = Field(exclude=True)  # assets/voices/*.wav — never leaves the backend
    ref_text: str | None = Field(default=None, exclude=True)  # optional clip transcript


class VoicesResponse(BaseModel):
    voices: list[Voice]


# ---- style LoRAs -------------------------------------------------------------------


class LoraStyle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    trigger: str
    base: str  # engine family the adapter was trained for ("wan-5b")
    created_at: datetime = Field(serialization_alias="createdAt")


class LorasResponse(BaseModel):
    loras: list[LoraStyle]


# ---- model catalog ---------------------------------------------------------------


class EngineInfo(BaseModel):
    id: str
    label: str
    tier: Literal["standard", "premium"]
    credits: str
    available: bool
    default: bool


class ModelsResponse(BaseModel):
    # keyed by JobKind value: talking_head / broll / image
    models: dict[str, list[EngineInfo]]
