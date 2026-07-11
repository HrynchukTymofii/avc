"""Image job processor: single-frame Wan2.2 diffusion -> PNG.

Progress map: diffusion 0-95 (from the denoising step callback), saving 95-100.
"""

from __future__ import annotations

import asyncio
import logging
import random

from app.config import Settings
from app.models_catalog import get_engine
from app.pipelines.manager import ModelManager
from app.queue.job import ImageParams, Job
from app.queue.worker import ProgressReporter
from app.schemas import JobKind

log = logging.getLogger(__name__)

_DIFFUSION_END = 95


class ImageProcessor:
    def __init__(self, manager: ModelManager, settings: Settings) -> None:
        self._manager = manager
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, ImageParams)

        out_path = self._settings.outputs_dir / job.id / "output.png"
        seed = random.randrange(2**31)

        engine = get_engine(JobKind.IMAGE, params.model)
        pipeline_name = engine.pipeline if engine else "wan"

        report(0, "diffusion")
        async with self._manager.acquire(pipeline_name) as pipe:
            await asyncio.to_thread(
                pipe.generate_image,
                prompt=params.prompt,
                orientation=params.orientation,
                out_path=out_path,
                on_progress=lambda f: report(int(f * _DIFFUSION_END), "diffusion"),
                seed=seed,
            )

        log.info("image complete", extra={"job_id": job.id, "seed": seed})
        return {"image": f"/outputs/{job.id}/output.png"}
