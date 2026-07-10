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


class JobCreatedResponse(BaseModel):
    job_id: str = Field(serialization_alias="jobId")


class ErrorResponse(BaseModel):
    detail: str


# ---- request text fields (from multipart forms) --------------------------------
# Length limits come from Settings and are enforced in services.validation, so the
# models here only pin the shape and the fixed product constraints.


class TalkingHeadRequest(BaseModel):
    script: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class BrollRequest(BaseModel):
    prompt: str = Field(min_length=1)
    duration: int = Field(ge=3, le=5)


# ---- status: discriminated union on `status` ------------------------------------


class QueuedStatus(BaseModel):
    status: Literal["queued"] = "queued"
    position: int = Field(ge=1)


class ProcessingStatus(BaseModel):
    status: Literal["processing"] = "processing"
    progress: int = Field(ge=0, le=100)
    stage: str


class FinishedStatus(BaseModel):
    # `audio` is talking-head only; routes serialize with exclude_none so B-roll
    # responses omit the key entirely rather than sending null.
    status: Literal["finished"] = "finished"
    video: str
    audio: str | None = None


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


class JobListResponse(BaseModel):
    jobs: list[JobSummary]


# ---- voices ------------------------------------------------------------------------


class Voice(BaseModel):
    id: str
    name: str
    language: str
    ref_audio: Path = Field(exclude=True)  # assets/voices/*.wav — never leaves the backend
    ref_text: str | None = Field(default=None, exclude=True)  # optional clip transcript


class VoicesResponse(BaseModel):
    voices: list[Voice]
