"""Job model: states, per-kind parameters, and the Job record itself.

The queue only ever carries job IDs; Job instances live in the JobStore, which is
the single source of truth for job state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

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


@dataclass
class BrollParams:
    prompt: str
    duration_s: int
    image_path: Path | None


@dataclass
class ImageParams:
    prompt: str
    orientation: str  # key of wan_pipeline.IMAGE_SIZES


JobParams = TalkingHeadParams | BrollParams | ImageParams


def new_job_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    kind: JobKind
    # None only for jobs rehydrated from disk after a restart — those are history
    # entries and are never reprocessed.
    params: JobParams | None
    label: str = ""
    state: JobState = JobState.QUEUED
    progress: int = 0
    stage: str | None = None
    error: str | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
