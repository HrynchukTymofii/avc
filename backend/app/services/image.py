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

        engine = get_engine(JobKind.IMAGE, params.model)
        pipeline_name = engine.pipeline if engine else "wan"
        count = max(1, params.count)

        urls: list[str] = []
        report(0, "diffusion")
        async with self._manager.acquire(pipeline_name) as pipe:
            for index in range(count):
                name = f"output_{index + 1}.png" if count > 1 else "output.png"
                seed = random.randrange(2**31)

                def on_progress(fraction: float, done: int = index) -> None:
                    report(int((done + fraction) / count * _DIFFUSION_END), "diffusion")

                await asyncio.to_thread(
                    pipe.generate_image,
                    prompt=params.prompt,
                    orientation=params.orientation,
                    out_path=self._settings.outputs_dir / job.id / name,
                    on_progress=on_progress,
                    seed=seed,
                )
                urls.append(f"/outputs/{job.id}/{name}")

        log.info("images complete", extra={"job_id": job.id, "count": count})
        # First image under the classic key; extras as image_2.. so the outputs
        # dict stays str->str for snapshots. The status route reassembles the list.
        outputs = {"image": urls[0]}
        for position, url in enumerate(urls[1:], start=2):
            outputs[f"image_{position}"] = url
        return outputs
