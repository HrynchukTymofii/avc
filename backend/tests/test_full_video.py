"""Full-video assembler orchestration: pipeline batching order, frame-grid
fitting, early voiceover publishing, and the progress plan — using fake
pipelines through the real ModelManager and a fake ffmpeg module."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.pipelines.manager import ModelManager
from app.queue.job import FullVideoParams, Job
from app.schemas import JobKind
from app.services import full_video as full_video_module
from app.services.full_video import FullVideoProcessor, build_progress_plan
from app.services.script_parser import SegmentKind, parse_full_video_script
from app.services.voices import VoiceRegistry
from tests.test_processors import (
    FakeMuseTalk,
    FakeS2,
    FakeWan,
    ProgressLog,
    build_manager,
    settings,  # noqa: F401  (fixture)
)
from tests.test_voices import entry, write_voices_json, write_wav


class SpyS2(FakeS2):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.texts: list[str] = []

    def generate(self, text, reference_audio, out_path, on_progress, reference_text=None):
        self.events.append("s2")
        self.texts.append(text)
        return super().generate(text, reference_audio, out_path, on_progress, reference_text)


class SpyWan(FakeWan):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.video_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def generate(self, prompt, duration_s, image_path, out_path, on_progress,
                 seed=None, orientation=None):
        self.events.append("wan")
        result = super().generate(
            prompt, duration_s, image_path, out_path, on_progress, seed, orientation
        )
        self.video_calls.append(self.last_call)
        return result

    def generate_image(self, prompt, orientation, out_path, on_progress, seed=None):
        self.events.append("wan-image")
        result = super().generate_image(prompt, orientation, out_path, on_progress, seed)
        self.image_calls.append(self.last_call)
        return result


class SpyMuseTalk(FakeMuseTalk):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.audio_paths: list[Path] = []

    def generate(self, avatar_path, audio_path, out_path, on_progress, driving_video_path=None):
        self.events.append("musetalk")
        self.audio_paths.append(Path(audio_path))
        return super().generate(avatar_path, audio_path, out_path, on_progress, driving_video_path)


class FakeFFmpeg:
    """Stands in for services.ffmpeg: canned durations, files written as
    markers, every call recorded in the shared event list."""

    def __init__(self, events: list[str], durations: dict[str, float], default_s: float = 2.0):
        self.events = events
        self.durations = durations
        self.default_s = default_s

    def _duration(self, src: Path) -> float:
        return self.durations.get(Path(src).name, self.default_s)

    async def probe_duration(self, src):
        self.events.append(f"probe:{Path(src).name}")
        return self._duration(src)

    async def pad_audio_to_duration(self, src, dst, *, duration_s):
        self.events.append("pad_audio")
        Path(dst).write_bytes(b"WAV")
        return Path(dst)

    async def concat_audio(self, sources, dst):
        assert all(Path(s).is_file() for s in sources)
        self.events.append("concat_audio")
        Path(dst).write_bytes(b"WAV")
        return Path(dst)

    async def still_to_clip(self, src, dst, *, duration_s, width, height, fps=24, zoom=1.12):
        assert Path(src).is_file()
        self.events.append("still_to_clip")
        Path(dst).write_bytes(b"VIDEO")
        return Path(dst)

    async def pingpong(self, src, dst):
        assert Path(src).is_file()
        self.events.append("pingpong")
        Path(dst).write_bytes(b"VIDEO")
        return Path(dst)

    async def loop_to_duration(self, src, dst, *, duration_s):
        assert Path(src).is_file()
        self.events.append("loop")
        Path(dst).write_bytes(b"VIDEO")
        return Path(dst)

    async def normalize_segment(self, src, dst, *, width, height, fps, duration_s):
        assert Path(src).is_file()
        self.events.append(f"normalize:{width}x{height}@{fps}")
        Path(dst).write_bytes(b"VIDEO")
        return Path(dst)

    async def concat_clips(self, sources, dst):
        assert all(Path(s).is_file() for s in sources)
        self.events.append(f"concat_clips:{len(sources)}")
        Path(dst).write_bytes(b"VIDEO")
        return Path(dst)

    async def mux_av(self, video_src, audio_src, dst):
        assert Path(video_src).is_file() and Path(audio_src).is_file()
        self.events.append("mux_av")
        Path(dst).write_bytes(b"FINAL")
        return Path(dst)


def spy_on_acquire(manager: ModelManager, acquired: list[str]) -> None:
    original = manager.acquire

    @asynccontextmanager
    async def wrapper(name: str):
        acquired.append(name)
        async with original(name) as pipeline:
            yield pipeline

    manager.acquire = wrapper  # type: ignore[method-assign]


def load_voices(settings) -> VoiceRegistry:
    write_wav(settings.assets_dir / "voices" / "en-test.wav")
    write_voices_json(settings.assets_dir, [entry()])
    voices = VoiceRegistry(settings.assets_dir)
    voices.load()
    return voices


MIXED_SCRIPT = (
    "[excited] Welcome to the show.\n"
    "[BROLL: aerial shot of a harbour]\n"
    "Ships arrive every morning. [short pause]\n"
    "[IMAGE: map of trade routes]\n"
    "The routes span three continents.\n"
    "[CLIP: tour.mp4]\n"
    "Here is our warehouse.\n"
    "[ONCAMERA]\n"
    "Thanks for watching."
)


def make_job(settings, script: str, *, job_id: str = "fv1", avatar: bool = True,
             clip_names: tuple[str, ...] = ()) -> Job:
    inputs = settings.outputs_dir / job_id / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    avatar_path = None
    if avatar:
        avatar_path = inputs / "avatar.png"
        avatar_path.write_bytes(b"PNG")
    clip_paths: dict[str, Path] = {}
    for k, name in enumerate(clip_names):
        clip_path = inputs / f"clip_{k}.mp4"
        clip_path.write_bytes(b"VIDEO")
        clip_paths[name.casefold()] = clip_path
    return Job(
        id=job_id,
        kind=JobKind.FULL_VIDEO,
        params=FullVideoParams(
            script=script, voice_id="en-test", avatar_path=avatar_path, clip_paths=clip_paths
        ),
    )


async def test_mixed_script_full_flow(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    # User clip is 1s (shorter than its ~2s segment) — must be plain-looped.
    fake_ffmpeg = FakeFFmpeg(events, durations={"clip_0.mp4": 1.0})
    monkeypatch.setattr(full_video_module, "ffmpeg", fake_ffmpeg)

    s2, wan, musetalk = SpyS2(events), SpyWan(events), SpyMuseTalk(events)
    manager = build_manager(s2, wan, musetalk)
    acquired: list[str] = []
    spy_on_acquire(manager, acquired)
    processor = FullVideoProcessor(manager, load_voices(settings), settings)

    job = make_job(settings, MIXED_SCRIPT, clip_names=("tour.mp4",))
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    assert outputs == {
        "video": "/outputs/fv1/output.mp4",
        "audio": "/outputs/fv1/voiceover.wav",
    }
    assert (settings.outputs_dir / "fv1" / "output.mp4").read_bytes() == b"FINAL"
    assert (settings.outputs_dir / "fv1" / "voiceover.wav").is_file()
    # intermediates removed on success
    assert not (settings.outputs_dir / "fv1" / "segments").exists()

    # one residency per pipeline, in swap-minimizing order
    assert acquired == ["s2", "wan", "musetalk"]

    # per-kind call counts match the script (5 segments, 1 broll, 1 image, 2 on-camera)
    assert events.count("s2") == 5
    assert events.count("wan") == 1
    assert events.count("wan-image") == 1
    assert events.count("musetalk") == 2
    assert s2.texts[0] == "[excited] Welcome to the show."  # voice tag kept
    assert wan.video_calls[0]["prompt"] == "aerial shot of a harbour"
    assert wan.video_calls[0]["duration_s"] == 3  # 2s narration clamped to Wan min
    assert wan.image_calls[0]["prompt"] == "map of trade routes"

    # voiceover published before any diffusion ran
    assert events.index("concat_audio") < events.index("wan")
    assert job.outputs["audio"] == "/outputs/fv1/voiceover.wav"

    # the short user clip was looped, never ping-ponged; b-roll (2s target,
    # 2s canned duration) needed neither
    assert events.count("loop") == 1
    assert events.count("pingpong") == 0
    assert events.count("still_to_clip") == 1
    # normalized: broll + clip + 2 on-camera (image comes canvas-exact from still_to_clip)
    assert sum(1 for e in events if e.startswith("normalize:")) == 4
    assert "concat_clips:5" in events
    assert events[-1] == "mux_av"

    assert progress.stages() == ["tts", "diffusion", "lip-sync", "encoding"]
    values = [p for p, _ in progress.events]
    assert values == sorted(values)  # progress never goes backwards
    assert values[0] == 2 and values[-1] <= 100


async def test_short_broll_is_pingponged_then_looped(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    # 7.3s narration → ~7.33s target; the 4s canned b-roll must be extended.
    fake_ffmpeg = FakeFFmpeg(
        events, durations={"00_speech.wav": 7.3, "00_broll_raw.mp4": 4.0}
    )
    monkeypatch.setattr(full_video_module, "ffmpeg", fake_ffmpeg)

    s2, wan = SpyS2(events), SpyWan(events)
    processor = FullVideoProcessor(build_manager(s2, wan), load_voices(settings), settings)
    job = make_job(settings, "[BROLL: waves] Long narration here.", job_id="fv2", avatar=False)

    await processor.process(job, ProgressLog())

    assert wan.video_calls[0]["duration_s"] == 5  # ceil(7.33) clamped to Wan max
    assert events.count("pingpong") == 1
    assert events.count("loop") == 1


async def test_all_broll_script_needs_no_avatar(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(full_video_module, "ffmpeg", FakeFFmpeg(events, durations={}))

    s2, wan = SpyS2(events), SpyWan(events)
    manager = build_manager(s2, wan)  # no musetalk registered at all
    acquired: list[str] = []
    spy_on_acquire(manager, acquired)
    processor = FullVideoProcessor(manager, load_voices(settings), settings)

    job = make_job(
        settings, "[BROLL: dunes] One. [BROLL: oasis] Two.", job_id="fv3", avatar=False
    )
    outputs = await processor.process(job, ProgressLog())

    assert outputs["video"] == "/outputs/fv3/output.mp4"
    assert acquired == ["s2", "wan"]


async def test_oncamera_without_avatar_fails(settings, monkeypatch) -> None:
    monkeypatch.setattr(full_video_module, "ffmpeg", FakeFFmpeg([], durations={}))
    processor = FullVideoProcessor(build_manager(SpyS2([])), load_voices(settings), settings)
    job = make_job(settings, "Just me talking.", job_id="fv4", avatar=False)

    with pytest.raises(ValueError, match="avatar image is required"):
        await processor.process(job, ProgressLog())


async def test_missing_clip_reference_fails_with_name(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(full_video_module, "ffmpeg", FakeFFmpeg(events, durations={}))
    processor = FullVideoProcessor(build_manager(SpyS2(events)), load_voices(settings), settings)
    # params built directly (bypassing the route's checks) with no clip uploads
    job = make_job(settings, "[CLIP: missing.mp4] Narration.", job_id="fv5", avatar=False)

    with pytest.raises(RuntimeError, match=r"segment 1 \(clip\).*missing\.mp4"):
        await processor.process(job, ProgressLog())


async def test_deleted_voice_fails_cleanly(settings, monkeypatch) -> None:
    monkeypatch.setattr(full_video_module, "ffmpeg", FakeFFmpeg([], durations={}))
    voices = VoiceRegistry(settings.assets_dir)  # empty registry
    voices.load()
    processor = FullVideoProcessor(build_manager(SpyS2([])), voices, settings)
    job = make_job(settings, "Hello.", job_id="fv6")

    with pytest.raises(ValueError, match="no longer available"):
        await processor.process(job, ProgressLog())


# ---- build_progress_plan ---------------------------------------------------------


def test_progress_plan_bands_are_monotone_and_bounded() -> None:
    segments = parse_full_video_script(MIXED_SCRIPT)
    bands = build_progress_plan(segments)

    ordered = list(bands.values())
    flat = [value for band in ordered for value in band]
    assert flat == sorted(flat)  # each band starts where the previous ended
    assert flat[0] == 2
    assert flat[-1] <= 96


def test_progress_plan_orders_tasks_by_pipeline() -> None:
    segments = parse_full_video_script(MIXED_SCRIPT)
    kinds = [task for task, _ in build_progress_plan(segments)]

    assert kinds[:5] == ["tts"] * 5
    assert kinds[5:] == ["broll", "image", "lipsync", "lipsync"]


def test_progress_plan_weights_brolls_heavier_than_tts() -> None:
    segments = parse_full_video_script("Short. [BROLL: x] Also short.")
    bands = build_progress_plan(segments)

    def width(key): return bands[key][1] - bands[key][0]

    assert width(("broll", 1)) > width(("tts", 0))


def test_progress_plan_covers_every_gpu_task() -> None:
    segments = parse_full_video_script(MIXED_SCRIPT)
    bands = build_progress_plan(segments)

    assert {key for key in bands} == {
        ("tts", 0), ("tts", 1), ("tts", 2), ("tts", 3), ("tts", 4),
        ("broll", 1), ("image", 2),
        ("lipsync", 0), ("lipsync", 4),
    }
    for kind in (SegmentKind.BROLL, SegmentKind.IMAGE):
        assert any(s.kind is kind for s in segments)
