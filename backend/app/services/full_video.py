"""Full-video assembler: tagged script -> talking head + b-roll + stills +
uploaded clips over one continuous voiceover.

Stages are batched BY PIPELINE, not by timeline order, so the model manager
satisfies each VRAM peak once: (1) all narration in one s2 residency; (2) all
b-roll clips then all stills in one wan residency (stills deliberately use
Wan's single-frame mode instead of FLUX — FLUX would evict Wan mid-job);
(3) all on-camera segments in one musetalk residency; (4) CPU-only ffmpeg
assembly.

A/V alignment uses frame-grid quantization: each segment's video is built to
exactly ceil(audio_duration * 24) / 24 seconds and its audio is silence-padded
to the same figure, so the concatenated video and concatenated audio line up
at every cut with zero cumulative drift.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import shutil
from pathlib import Path

from app.config import Settings
from app.pipelines.manager import ModelManager
from app.pipelines.wan_pipeline import IMAGE_SIZES
from app.queue.job import FullVideoParams, Job
from app.queue.worker import ProgressReporter
from app.services import ffmpeg
from app.services.script_parser import (
    ScriptSegment,
    SegmentKind,
    parse_full_video_script,
)
from app.services.voices import VoiceRegistry

log = logging.getLogger(__name__)

_CANVAS_FPS = 24
_WAN_MIN_S, _WAN_MAX_S = 3, 5

_PLAN_START = 2
_ASSEMBLY_START = 96  # 96..100 is the fixed ffmpeg-assembly band

# Relative cost of one unit of each task type; TTS and lip-sync scale with the
# narration length (400 chars is S2's chunk size, a proxy for both).
_TTS_WEIGHT = 1.0
_BROLL_WEIGHT = 8.0
_IMAGE_WEIGHT = 3.0
_LIPSYNC_WEIGHT = 3.0

ProgressBand = tuple[int, int]


def _text_scale(segment: ScriptSegment) -> float:
    return 1.0 + len(segment.text) / 400


def build_progress_plan(
    segments: list[ScriptSegment],
) -> dict[tuple[str, int], ProgressBand]:
    """Split the 2..96 progress span across every GPU task, proportionally to
    its weight, in execution order (all tts, then broll, then image, then
    lip-sync). Keyed by (task, segment_index); bands are monotone by
    construction."""
    tasks: list[tuple[str, int, float]] = []
    for i, segment in enumerate(segments):
        tasks.append(("tts", i, _TTS_WEIGHT * _text_scale(segment)))
    for i, segment in enumerate(segments):
        if segment.kind is SegmentKind.BROLL:
            tasks.append(("broll", i, _BROLL_WEIGHT))
    for i, segment in enumerate(segments):
        if segment.kind is SegmentKind.IMAGE:
            tasks.append(("image", i, _IMAGE_WEIGHT))
    for i, segment in enumerate(segments):
        if segment.kind is SegmentKind.ONCAMERA:
            tasks.append(("lipsync", i, _LIPSYNC_WEIGHT * _text_scale(segment)))

    total = sum(weight for _, _, weight in tasks)
    span = _ASSEMBLY_START - _PLAN_START
    bands: dict[tuple[str, int], ProgressBand] = {}
    cursor = float(_PLAN_START)
    for task, i, weight in tasks:
        start = cursor
        cursor += span * (weight / total)
        bands[(task, i)] = (int(start), int(cursor))
    return bands


def _band_progress(
    report: ProgressReporter, band: ProgressBand, stage: str
):
    start, end = band
    return lambda fraction: report(start + int(fraction * (end - start)), stage)


class FullVideoProcessor:
    def __init__(
        self, manager: ModelManager, voices: VoiceRegistry, settings: Settings
    ) -> None:
        self._manager = manager
        self._voices = voices
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, FullVideoParams)

        # Authoritative re-parse; the route already validated, so failures here
        # surface the same user-safe message.
        segments = parse_full_video_script(params.script)

        voice = self._voices.get(params.voice_id)
        if voice is None:
            raise ValueError(
                f"voice {params.voice_id!r} is no longer available — pick another voice"
            )
        oncamera = [i for i, s in enumerate(segments) if s.kind is SegmentKind.ONCAMERA]
        broll = [i for i, s in enumerate(segments) if s.kind is SegmentKind.BROLL]
        images = [i for i, s in enumerate(segments) if s.kind is SegmentKind.IMAGE]
        if oncamera and params.avatar_path is None:
            raise ValueError("avatar image is required — the script has on-camera segments")

        canvas_height, canvas_width = IMAGE_SIZES[params.orientation]
        job_dir = self._settings.outputs_dir / job.id
        work = job_dir / "segments"
        work.mkdir(parents=True, exist_ok=True)
        bands = build_progress_plan(segments)

        # ---- 1: narration — every segment's speech in one s2 residency --------
        report(_PLAN_START, "tts")
        speech: list[Path] = []
        async with self._manager.acquire("s2") as s2:
            for i, segment in enumerate(segments):
                out_path = work / f"{i:02d}_speech.wav"
                await asyncio.to_thread(
                    s2.generate,
                    text=segment.text,
                    reference_audio=voice.ref_audio,
                    out_path=out_path,
                    on_progress=_band_progress(report, bands[("tts", i)], "tts"),
                    reference_text=voice.ref_text,
                )
                speech.append(out_path)

        # Frame-grid targets: round each segment UP to the 24 fps grid so video
        # (built to the grid) and audio (padded to it) align at every cut.
        targets: list[float] = []
        for wav in speech:
            duration = await ffmpeg.probe_duration(wav)
            targets.append(max(1, math.ceil(duration * _CANVAS_FPS)) / _CANVAS_FPS)

        voiceover_path = job_dir / "voiceover.wav"
        padded: list[Path] = []
        for i, wav in enumerate(speech):
            padded_path = work / f"{i:02d}_padded.wav"
            await ffmpeg.pad_audio_to_duration(wav, padded_path, duration_s=targets[i])
            padded.append(padded_path)
        await ffmpeg.concat_audio(padded, voiceover_path)

        # Publish the voiceover as soon as it exists so the UI can offer it
        # while diffusion is still running. Safe: process() runs on the event
        # loop and this Job is the store's live record.
        audio_url = f"/outputs/{job.id}/voiceover.wav"
        job.outputs["audio"] = audio_url

        # ---- 2: all AI visuals in one wan residency ---------------------------
        broll_raw: dict[int, Path] = {}
        stills: dict[int, Path] = {}
        if broll or images:
            first_band = bands[("broll", broll[0])] if broll else bands[("image", images[0])]
            report(first_band[0], "diffusion")
            async with self._manager.acquire("wan") as wan:
                for i in broll:
                    out_path = work / f"{i:02d}_broll_raw.mp4"
                    await asyncio.to_thread(
                        wan.generate,
                        prompt=segments[i].prompt,
                        duration_s=min(_WAN_MAX_S, max(_WAN_MIN_S, math.ceil(targets[i]))),
                        image_path=None,
                        out_path=out_path,
                        on_progress=_band_progress(report, bands[("broll", i)], "diffusion"),
                        seed=random.randrange(2**31),
                        orientation=params.orientation,
                    )
                    broll_raw[i] = out_path
                for i in images:
                    out_path = work / f"{i:02d}_still.png"
                    await asyncio.to_thread(
                        wan.generate_image,
                        prompt=segments[i].prompt,
                        orientation=params.orientation,
                        out_path=out_path,
                        on_progress=_band_progress(report, bands[("image", i)], "diffusion"),
                        seed=random.randrange(2**31),
                    )
                    stills[i] = out_path

        # ---- 3: all on-camera segments in one musetalk residency --------------
        lipsync_raw: dict[int, Path] = {}
        if oncamera:
            report(bands[("lipsync", oncamera[0])][0], "lip-sync")
            async with self._manager.acquire("musetalk") as musetalk:
                for i in oncamera:
                    out_path = work / f"{i:02d}_lipsync_raw.mp4"
                    await asyncio.to_thread(
                        musetalk.generate,
                        avatar_path=params.avatar_path,
                        audio_path=speech[i],
                        out_path=out_path,
                        on_progress=_band_progress(report, bands[("lipsync", i)], "lip-sync"),
                    )
                    lipsync_raw[i] = out_path

        # ---- 4: CPU-only assembly ---------------------------------------------
        report(_ASSEMBLY_START, "encoding")
        segment_clips: list[Path] = []
        for i, segment in enumerate(segments):
            try:
                clip = await self._fit_segment(
                    index=i,
                    segment=segment,
                    target_s=targets[i],
                    work=work,
                    canvas=(canvas_width, canvas_height),
                    broll_raw=broll_raw,
                    stills=stills,
                    lipsync_raw=lipsync_raw,
                    clip_paths=params.clip_paths,
                )
            except Exception as exc:
                raise RuntimeError(f"segment {i + 1} ({segment.kind.value}): {exc}") from exc
            segment_clips.append(clip)
            report(
                _ASSEMBLY_START + int((i + 1) / len(segments) * (99 - _ASSEMBLY_START)),
                "encoding",
            )

        concat_path = work / "video_concat.mp4"
        final_path = job_dir / "output.mp4"
        await ffmpeg.concat_clips(segment_clips, concat_path)
        await ffmpeg.mux_av(concat_path, voiceover_path, final_path)

        # Intermediates are deleted on success only; a failed job leaves them
        # behind under segments/ for debugging.
        shutil.rmtree(work, ignore_errors=True)

        return {
            "video": f"/outputs/{job.id}/output.mp4",
            "audio": audio_url,
        }

    async def _fit_segment(
        self,
        *,
        index: int,
        segment: ScriptSegment,
        target_s: float,
        work: Path,
        canvas: tuple[int, int],
        broll_raw: dict[int, Path],
        stills: dict[int, Path],
        lipsync_raw: dict[int, Path],
        clip_paths: dict[str, Path],
    ) -> Path:
        """Produce this segment's canvas-conformed clip of exactly target_s."""
        width, height = canvas
        out_path = work / f"{index:02d}_seg.mp4"

        if segment.kind is SegmentKind.IMAGE:
            # still_to_clip already emits canvas-exact H.264 — no normalize pass.
            return await ffmpeg.still_to_clip(
                stills[index],
                out_path,
                duration_s=target_s,
                width=width,
                height=height,
                fps=_CANVAS_FPS,
            )

        if segment.kind is SegmentKind.BROLL:
            src = broll_raw[index]
            if await ffmpeg.probe_duration(src) < target_s - 1e-3:
                # Ping-pong hides the loop point (diffusion motion reverses
                # invisibly), then repeat as needed.
                pingponged = work / f"{index:02d}_pingpong.mp4"
                await ffmpeg.pingpong(src, pingponged)
                looped = work / f"{index:02d}_looped.mp4"
                src = await ffmpeg.loop_to_duration(pingponged, looped, duration_s=target_s)
        elif segment.kind is SegmentKind.CLIP:
            assert segment.clip_name is not None
            try:
                src = clip_paths[segment.clip_name.casefold()]
            except KeyError:
                raise ValueError(
                    f"uploaded clip {segment.clip_name!r} was not found"
                ) from None
            if await ffmpeg.probe_duration(src) < target_s - 1e-3:
                # Real footage played backwards is noticeable — plain repeat.
                looped = work / f"{index:02d}_looped.mp4"
                src = await ffmpeg.loop_to_duration(src, looped, duration_s=target_s)
        else:  # ONCAMERA
            src = lipsync_raw[index]

        return await ffmpeg.normalize_segment(
            src,
            out_path,
            width=width,
            height=height,
            fps=_CANVAS_FPS,
            duration_s=target_s,
        )
