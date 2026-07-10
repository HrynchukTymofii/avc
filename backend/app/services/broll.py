"""B-roll job processor: Wan2.2 diffusion -> FFmpeg H.264 encode.

Progress map: diffusion 0-90 (from the denoising step callback), encoding 90-100.
"""

from __future__ import annotations

import asyncio
import logging
import random

from app.config import Settings
from app.pipelines.manager import ModelManager
from app.queue.job import BrollParams, Job
from app.queue.worker import ProgressReporter
from app.services import ffmpeg

log = logging.getLogger(__name__)

_DIFFUSION_END = 90


class BrollProcessor:
    def __init__(self, manager: ModelManager, settings: Settings) -> None:
        self._manager = manager
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, BrollParams)

        job_dir = self._settings.outputs_dir / job.id
        raw_path = job_dir / "diffusion_raw.mp4"
        final_path = job_dir / "output.mp4"
        seed = random.randrange(2**31)

        report(0, "diffusion")
        async with self._manager.acquire("wan") as wan:
            await asyncio.to_thread(
                wan.generate,
                prompt=params.prompt,
                duration_s=params.duration_s,
                image_path=params.image_path,
                out_path=raw_path,
                on_progress=lambda f: report(int(f * _DIFFUSION_END), "diffusion"),
                seed=seed,
            )

        report(_DIFFUSION_END, "encoding")
        await ffmpeg.encode_h264(raw_path, final_path)
        raw_path.unlink(missing_ok=True)

        log.info("b-roll complete", extra={"job_id": job.id, "seed": seed})
        return {"video": f"/outputs/{job.id}/output.mp4"}
