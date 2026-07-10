"""Talking-head job processor: S2 speech -> MuseTalk lip-sync -> FFmpeg mux.

Progress map: tts 2-30, lip-sync 30-90, encoding 90-100. Pipelines are acquired
sequentially (never nested) so the model manager only has to satisfy one active
pipeline's VRAM peak at a time.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import Settings
from app.pipelines.manager import ModelManager
from app.queue.job import Job, TalkingHeadParams
from app.queue.worker import ProgressReporter
from app.services import ffmpeg
from app.services.voices import VoiceRegistry

log = logging.getLogger(__name__)

_TTS_START, _TTS_END = 2, 30
_SYNC_END = 90


class TalkingHeadProcessor:
    def __init__(
        self, manager: ModelManager, voices: VoiceRegistry, settings: Settings
    ) -> None:
        self._manager = manager
        self._voices = voices
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, TalkingHeadParams)

        voice = self._voices.get(params.voice_id)
        if voice is None:
            raise ValueError(
                f"voice {params.voice_id!r} is no longer available — pick another voice"
            )

        job_dir = self._settings.outputs_dir / job.id
        speech_path = job_dir / "speech.wav"
        raw_video_path = job_dir / "lipsync_raw.mp4"
        final_path = job_dir / "output.mp4"

        # Voice-only jobs spend their whole budget on TTS; full jobs hand off
        # to lip-sync at _TTS_END.
        tts_end = 95 if params.voice_only else _TTS_END

        report(_TTS_START, "tts")
        async with self._manager.acquire("s2") as s2:
            await asyncio.to_thread(
                s2.generate,
                text=params.script,
                reference_audio=voice.ref_audio,
                out_path=speech_path,
                on_progress=lambda f: report(
                    _TTS_START + int(f * (tts_end - _TTS_START)), "tts"
                ),
                reference_text=voice.ref_text,
            )

        # Publish the voice track as soon as it exists so the UI can offer the
        # WAV while lip-sync is still running. Safe: process() runs on the
        # event loop and this Job is the store's live record; the next progress
        # update persists it.
        audio_url = f"/outputs/{job.id}/speech.wav"
        job.outputs["audio"] = audio_url

        if params.voice_only:
            return {"audio": audio_url}
        if params.avatar_path is None:
            raise ValueError("avatar image is required for video generation")

        report(_TTS_END, "lip-sync")
        async with self._manager.acquire("musetalk") as musetalk:
            await asyncio.to_thread(
                musetalk.generate,
                avatar_path=params.avatar_path,
                audio_path=speech_path,
                out_path=raw_video_path,
                on_progress=lambda f: report(
                    _TTS_END + int(f * (_SYNC_END - _TTS_END)), "lip-sync"
                ),
            )

        report(_SYNC_END, "encoding")
        await ffmpeg.mux_av(raw_video_path, speech_path, final_path)
        raw_video_path.unlink(missing_ok=True)  # keep only the final artifacts

        return {
            "video": f"/outputs/{job.id}/output.mp4",
            "audio": audio_url,
        }
