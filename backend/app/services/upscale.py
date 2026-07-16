"""Upscale job processor: Real-ESRGAN on one image, or frame-by-frame on a video.

Images: upscale 5-95, save to output.png.
Videos: frame extraction 0-10, per-frame upscaling 10-85, reassembly (with the
source's audio track carried over) 85-100. The lossless PNG frame intermediates
can be large; both frame directories are deleted once the MP4 exists.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from app.config import Settings
from app.models_catalog import get_engine
from app.pipelines.manager import ModelManager
from app.queue.job import Job, UpscaleParams
from app.queue.worker import ProgressReporter
from app.schemas import JobKind
from app.services import ffmpeg

log = logging.getLogger(__name__)

_FRAMES_START = 10
_FRAMES_END = 85


class UpscaleProcessor:
    def __init__(self, manager: ModelManager, settings: Settings) -> None:
        self._manager = manager
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, UpscaleParams)

        engine = get_engine(JobKind.UPSCALE, params.model)
        pipeline_name = engine.pipeline if engine else "upscale"

        if params.media == "image":
            return await self._process_image(job, params, pipeline_name, report)
        return await self._process_video(job, params, pipeline_name, report)

    async def _process_image(
        self,
        job: Job,
        params: UpscaleParams,
        pipeline_name: str,
        report: ProgressReporter,
    ) -> dict[str, str]:
        out_path = self._settings.outputs_dir / job.id / "output.png"
        report(5, "upscaling")
        async with self._manager.acquire(pipeline_name) as pipe:
            await asyncio.to_thread(
                pipe.upscale_image,
                params.media_path,
                out_path,
                variant=params.variant,
                scale=params.scale,
            )
        log.info(
            "image upscaled",
            extra={"job_id": job.id, "variant": params.variant, "scale": params.scale},
        )
        return {"image": f"/outputs/{job.id}/output.png"}

    async def _process_video(
        self,
        job: Job,
        params: UpscaleParams,
        pipeline_name: str,
        report: ProgressReporter,
    ) -> dict[str, str]:
        job_dir = self._settings.outputs_dir / job.id
        frames_dir = job_dir / "frames"
        upscaled_dir = job_dir / "frames_up"
        out_path = job_dir / "output.mp4"

        report(0, "extracting frames")
        fps = await ffmpeg.probe_fps(params.media_path)
        frames = await ffmpeg.extract_frames(params.media_path, frames_dir)

        report(_FRAMES_START, "upscaling")
        try:
            async with self._manager.acquire(pipeline_name) as pipe:
                for index, frame in enumerate(frames):
                    await asyncio.to_thread(
                        pipe.upscale_image,
                        frame,
                        upscaled_dir / frame.name,
                        variant=params.variant,
                        scale=params.scale,
                    )
                    progress = _FRAMES_START + (index + 1) / len(frames) * (
                        _FRAMES_END - _FRAMES_START
                    )
                    report(int(progress), "upscaling")

            report(_FRAMES_END, "encoding")
            await ffmpeg.frames_to_video(
                upscaled_dir, out_path, fps=fps, audio_src=params.media_path
            )
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)
            shutil.rmtree(upscaled_dir, ignore_errors=True)

        log.info(
            "video upscaled",
            extra={
                "job_id": job.id,
                "frames": len(frames),
                "fps": round(fps, 3),
                "variant": params.variant,
                "scale": params.scale,
            },
        )
        return {"video": f"/outputs/{job.id}/output.mp4"}
