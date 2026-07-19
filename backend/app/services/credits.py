"""Credit pricing and the balance gate.

Every account has a credit allowance (User.credits in the frontend DB, default
100 for new sign-ups; raise it in the Neon console to top an account up). Jobs
are priced here at submission, the price is stored on the Job, and spending is
the sum of non-failed job costs — so failed jobs refund themselves and price
changes never rewrite history. Admins are exempt.

Prices must agree with the display hints in models_catalog (Engine.credits).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from fastapi import HTTPException

from app.models_catalog import Engine
from app.queue.job_store import JobStore
from app.services.auth import AuthUser
from app.services.script_parser import ScriptSegment, SegmentKind

# ~900 chars of spoken English per minute (same pace max_script_chars assumes).
_CHARS_PER_MINUTE = 900


def _script_minutes(script: str) -> int:
    return max(1, math.ceil(len(script) / _CHARS_PER_MINUTE))


def talking_head_cost(engine: Engine, script: str, voice_only: bool) -> int:
    minutes = _script_minutes(script)
    if voice_only:
        return minutes  # TTS only, no lip-sync GPU time
    if engine.id == "musetalk-animate":
        return 4 * minutes + 10  # "4 / min + 10"
    if engine.id == "wan-s2v-14b":
        return 40 * minutes  # "40 / min"
    return 2 * minutes  # musetalk, "2 / min"


def broll_cost(engine: Engine) -> int:
    # "8 / clip" standard; premium engines per their catalog hints.
    return {"wan-a14b": 30, "wan-animate-14b": 40}.get(engine.id, 8)


def image_cost(engine: Engine, count: int) -> int:
    # Kontext runs 28 steps on a 12B transformer — far heavier than schnell's 4.
    per_image = {"flux-schnell": 2, "flux-kontext": 4}.get(engine.id, 1)
    return per_image * count


def full_video_cost(segments: Iterable[ScriptSegment], script: str) -> int:
    # "varies / script": narration at the lip-sync rate plus each generated
    # visual at its own price. Uploaded [CLIP: …] footage is free.
    cost = 2 * _script_minutes(script)
    for segment in segments:
        if segment.kind is SegmentKind.BROLL:
            cost += 8
        elif segment.kind is SegmentKind.IMAGE:
            cost += 1
    return cost


def upscale_cost(media: str) -> int:
    return 10 if media == "video" else 1  # "1 / image · 10 / video"


def lora_training_cost() -> int:
    return 100  # "100 / run"


def require_credits(user: AuthUser, cost: int, store: JobStore) -> None:
    """403 unless the user can afford `cost`. Admins generate for free."""
    if user.role == "admin":
        return
    balance = user.credits - store.credits_spent(user.id)
    if cost > balance:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Not enough credits — this job costs {cost} and you have "
                f"{max(balance, 0)} left. Ask the admin for a top-up."
            ),
        )
