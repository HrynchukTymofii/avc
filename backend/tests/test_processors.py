"""Processor orchestration: staged progress, sequential pipeline acquisition, and
output contracts — using fake pipelines through the real ModelManager and
stubbed FFmpeg calls."""

from pathlib import Path

import pytest

from app.config import Settings
from app.pipelines.base import ManagedPipeline, PipelineState
from app.pipelines.manager import ModelManager
from app.queue.job import BrollParams, ImageParams, Job, TalkingHeadParams, new_job_id
from app.schemas import JobKind
from app.services import broll as broll_module
from app.services import talking_head as talking_head_module
from app.services.broll import BrollProcessor
from app.services.image import ImageProcessor
from app.services.talking_head import TalkingHeadProcessor
from app.services.voices import VoiceRegistry
from tests.test_voices import entry, write_voices_json, write_wav


class FakeS2(ManagedPipeline):
    def __init__(self) -> None:
        super().__init__("s2", vram_estimate_gb=10, vram_peak_gb=12, offload_policy="cpu")

    def load(self) -> None: ...
    def to_gpu(self) -> None: ...
    def to_cpu(self) -> None: ...
    def unload(self) -> None: ...

    def generate(self, text, reference_audio, out_path, on_progress, reference_text=None):
        assert Path(reference_audio).is_file()
        on_progress(0.5)
        on_progress(1.0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"WAV")
        return out_path


class FakeMuseTalk(ManagedPipeline):
    def __init__(self) -> None:
        super().__init__("musetalk", vram_estimate_gb=6, vram_peak_gb=8, offload_policy="cpu")
        self.last_driving_video = None

    def load(self) -> None: ...
    def to_gpu(self) -> None: ...
    def to_cpu(self) -> None: ...
    def unload(self) -> None: ...

    def generate(self, avatar_path, audio_path, out_path, on_progress, driving_video_path=None):
        assert Path(avatar_path).is_file()
        assert Path(audio_path).is_file()  # speech must exist before lip-sync
        if driving_video_path is not None:
            assert Path(driving_video_path).is_file()  # motion clip must exist first
        self.last_driving_video = driving_video_path
        on_progress(1.0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"VIDEO")
        return out_path


class FakeWan(ManagedPipeline):
    def __init__(self) -> None:
        super().__init__("wan", vram_estimate_gb=18, vram_peak_gb=26, offload_policy="cpu")
        self.last_call: dict = {}

    def load(self) -> None: ...
    def to_gpu(self) -> None: ...
    def to_cpu(self) -> None: ...
    def unload(self) -> None: ...

    def generate(
        self, prompt, duration_s, image_path, out_path, on_progress, seed=None, orientation=None
    ):
        self.last_call = {
            "prompt": prompt,
            "duration_s": duration_s,
            "image_path": image_path,
            "orientation": orientation,
        }
        on_progress(0.25)
        on_progress(1.0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"VIDEO")
        return out_path

    def generate_image(self, prompt, orientation, out_path, on_progress, seed=None):
        self.last_call = {"prompt": prompt, "orientation": orientation}
        on_progress(0.5)
        on_progress(1.0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"PNG")
        return out_path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
    )


@pytest.fixture
def stub_ffmpeg(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_mux_av(video_src, audio_src, dst):
        assert Path(video_src).is_file() and Path(audio_src).is_file()
        Path(dst).write_bytes(b"FINAL")
        calls.append("mux_av")
        return dst

    async def fake_encode_h264(src, dst, fps=None):
        assert Path(src).is_file()
        Path(dst).write_bytes(b"FINAL")
        calls.append("encode_h264")
        return dst

    monkeypatch.setattr(talking_head_module.ffmpeg, "mux_av", fake_mux_av)
    monkeypatch.setattr(broll_module.ffmpeg, "encode_h264", fake_encode_h264)
    return calls


def build_manager(*pipelines: ManagedPipeline) -> ModelManager:
    return ModelManager(
        pipelines,
        vram_reserve_gb=2.0,
        vram_probe=lambda: 48.0,
        clear_cuda_cache=lambda: None,
    )


class ProgressLog:
    def __init__(self) -> None:
        self.events: list[tuple[int, str]] = []

    def __call__(self, progress: int, stage: str) -> None:
        self.events.append((progress, stage))

    def stages(self) -> list[str]:
        seen: list[str] = []
        for _, stage in self.events:
            if not seen or seen[-1] != stage:
                seen.append(stage)
        return seen


async def test_talking_head_full_flow(settings: Settings, stub_ffmpeg) -> None:
    assets = settings.assets_dir
    write_wav(assets / "voices" / "en-test.wav")
    write_voices_json(assets, [entry()])
    voices = VoiceRegistry(assets)
    voices.load()

    s2, musetalk = FakeS2(), FakeMuseTalk()
    manager = build_manager(s2, musetalk)
    processor = TalkingHeadProcessor(manager, voices, settings)

    avatar = settings.outputs_dir / "job1" / "inputs" / "avatar.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_bytes(b"PNG")
    job = Job(
        id="job1",
        kind=JobKind.TALKING_HEAD,
        params=TalkingHeadParams(avatar_path=avatar, script="Hello world.", voice_id="en-test"),
    )
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    assert outputs == {"video": "/outputs/job1/output.mp4", "audio": "/outputs/job1/speech.wav"}
    assert (settings.outputs_dir / "job1" / "output.mp4").read_bytes() == b"FINAL"
    assert (settings.outputs_dir / "job1" / "speech.wav").is_file()
    assert not (settings.outputs_dir / "job1" / "lipsync_raw.mp4").exists()  # cleaned up

    assert progress.stages() == ["tts", "lip-sync", "encoding"]
    values = [p for p, _ in progress.events]
    assert values == sorted(values)  # progress never goes backwards

    # both pipelines were used and stay hot afterwards
    assert s2.state is PipelineState.ON_GPU
    assert musetalk.state is PipelineState.ON_GPU
    assert stub_ffmpeg == ["mux_av"]


async def test_talking_head_fails_cleanly_on_deleted_voice(
    settings: Settings, stub_ffmpeg
) -> None:
    voices = VoiceRegistry(settings.assets_dir)  # empty registry
    voices.load()
    processor = TalkingHeadProcessor(build_manager(FakeS2(), FakeMuseTalk()), voices, settings)

    job = Job(
        id="job2",
        kind=JobKind.TALKING_HEAD,
        params=TalkingHeadParams(avatar_path=Path("x.png"), script="Hi.", voice_id="gone"),
    )
    with pytest.raises(ValueError, match="no longer available"):
        await processor.process(job, ProgressLog())


async def test_talking_head_animate_flow(settings: Settings, stub_ffmpeg) -> None:
    from PIL import Image

    assets = settings.assets_dir
    write_wav(assets / "voices" / "en-test.wav")
    write_voices_json(assets, [entry()])
    voices = VoiceRegistry(assets)
    voices.load()

    s2, musetalk, wan = FakeS2(), FakeMuseTalk(), FakeWan()
    processor = TalkingHeadProcessor(build_manager(s2, musetalk, wan), voices, settings)

    avatar = settings.outputs_dir / "job6" / "inputs" / "avatar.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 600)).save(avatar)  # portrait aspect
    job = Job(
        id="job6",
        kind=JobKind.TALKING_HEAD,
        params=TalkingHeadParams(
            avatar_path=avatar, script="Hello world.", voice_id="en-test", animate=True
        ),
    )
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    assert outputs["video"] == "/outputs/job6/output.mp4"
    assert progress.stages() == ["tts", "motion", "lip-sync", "encoding"]
    assert wan.last_call["image_path"] == avatar
    assert wan.last_call["orientation"] == "portrait"
    assert musetalk.last_driving_video == settings.outputs_dir / "job6" / "idle_motion.mp4"
    values = [p for p, _ in progress.events]
    assert values == sorted(values)  # progress never goes backwards


def test_pingpong_cycle_loops_without_jump() -> None:
    from app.pipelines.musetalk_pipeline import _pingpong_cycle

    cycle = _pingpong_cycle(4)
    assert [cycle(i) for i in range(10)] == [0, 1, 2, 3, 2, 1, 0, 1, 2, 3]
    single = _pingpong_cycle(1)
    assert [single(i) for i in range(3)] == [0, 0, 0]


async def test_broll_t2v_flow(settings: Settings, stub_ffmpeg) -> None:
    wan = FakeWan()
    processor = BrollProcessor(build_manager(wan), settings)
    job = Job(
        id="job3",
        kind=JobKind.BROLL,
        params=BrollParams(prompt="a foggy harbour at dawn", duration_s=4, image_path=None),
    )
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    assert outputs == {"video": "/outputs/job3/output.mp4"}
    assert wan.last_call["prompt"] == "a foggy harbour at dawn"
    assert wan.last_call["duration_s"] == 4
    assert wan.last_call["image_path"] is None
    assert progress.stages() == ["diffusion", "encoding"]
    assert stub_ffmpeg == ["encode_h264"]
    assert not (settings.outputs_dir / "job3" / "diffusion_raw.mp4").exists()


async def test_broll_i2v_passes_reference_image(settings: Settings, stub_ffmpeg) -> None:
    wan = FakeWan()
    processor = BrollProcessor(build_manager(wan), settings)
    ref = settings.outputs_dir / "job4" / "inputs" / "reference.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"PNG")
    job = Job(
        id="job4",
        kind=JobKind.BROLL,
        params=BrollParams(prompt="animate this", duration_s=3, image_path=ref),
    )

    await processor.process(job, ProgressLog())
    assert wan.last_call["image_path"] == ref


async def test_image_flow(settings: Settings) -> None:
    wan = FakeWan()
    processor = ImageProcessor(build_manager(wan), settings)
    job = Job(
        id="job5",
        kind=JobKind.IMAGE,
        params=ImageParams(prompt="a lighthouse at dusk", orientation="portrait"),
    )
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    assert outputs == {"image": "/outputs/job5/output.png"}
    assert (settings.outputs_dir / "job5" / "output.png").read_bytes() == b"PNG"
    assert wan.last_call == {"prompt": "a lighthouse at dusk", "orientation": "portrait"}
    assert progress.stages() == ["diffusion"]
    values = [p for p, _ in progress.events]
    assert values == sorted(values)


def test_image_sizes_are_vae_compatible() -> None:
    from app.pipelines.wan_pipeline import IMAGE_SIZES

    for height, width in IMAGE_SIZES.values():
        assert height % 16 == 0 and width % 16 == 0


def test_wan_frame_count_is_valid_for_causal_vae() -> None:
    from app.pipelines.wan_pipeline import frames_for_duration

    assert frames_for_duration(3) == 73
    assert frames_for_duration(4) == 97
    assert frames_for_duration(5) == 121
    for seconds in (3, 4, 5):
        assert (frames_for_duration(seconds) - 1) % 4 == 0


def test_split_script_chunks_sensibly() -> None:
    from app.pipelines.s2_pipeline import split_script

    text = "First sentence. Second one! Third? " + "Word " * 200 + "."
    chunks = split_script(text, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert chunks[0].startswith("First sentence.")
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    assert split_script("   ") == []
    assert split_script("One tiny script.") == ["One tiny script."]
