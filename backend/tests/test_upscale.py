"""Upscale: mixed-media upload validation, the /api/upscale route, ffmpeg frame
round-trip, and the processor against a fake pipeline."""

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.pipelines.base import ManagedPipeline
from app.pipelines.manager import ModelManager
from app.queue.job import Job, UpscaleParams, new_job_id
from app.schemas import JobKind
from app.services import ffmpeg
from app.services import upscale as upscale_module
from app.services.upscale import UpscaleProcessor
from app.services.validation import InputValidationError, read_media_upload
from tests.test_processors import ProgressLog, build_manager


def png_bytes(size: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


# ---- read_media_upload ----------------------------------------------------------


class FakeUpload:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


async def test_read_media_upload_detects_image() -> None:
    data, ext, kind = await read_media_upload(
        FakeUpload(png_bytes()), max_image_bytes=10**6, max_video_bytes=10**7, field="file"
    )
    assert (ext, kind) == (".png", "image")
    assert data == png_bytes()


async def test_read_media_upload_detects_video() -> None:
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
    _, ext, kind = await read_media_upload(
        FakeUpload(mp4), max_image_bytes=10**6, max_video_bytes=10**7, field="file"
    )
    assert (ext, kind) == (".mp4", "video")


async def test_read_media_upload_image_gets_image_cap() -> None:
    big_image = png_bytes(512)
    with pytest.raises(InputValidationError, match="image size limit"):
        await read_media_upload(
            FakeUpload(big_image),
            max_image_bytes=100,  # image cap is tiny…
            max_video_bytes=10**7,  # …the video cap would have let it through
            field="file",
        )


async def test_read_media_upload_rejects_garbage() -> None:
    with pytest.raises(InputValidationError, match="PNG/JPEG image or an MP4"):
        await read_media_upload(
            FakeUpload(b"garbage bytes here"),
            max_image_bytes=10**6,
            max_video_bytes=10**7,
            field="file",
        )


# ---- POST /api/upscale ------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
        upscale_max_image_mp=1.0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_upscale_accepts_image(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/upscale",
        data={"model": "realesrgan-anime", "scale": "2"},
        files={"file": ("art.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    assert (tmp_path / "outputs" / job_id / "inputs" / "source.png").is_file()

    jobs = client.get("/api/jobs?kind=upscale").json()["jobs"]
    assert any(j["jobId"] == job_id for j in jobs)


def test_upscale_rejects_bad_scale(client: TestClient) -> None:
    response = client.post(
        "/api/upscale",
        data={"scale": "3"},
        files={"file": ("art.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 422
    assert "scale must be" in response.json()["detail"]


def test_upscale_rejects_huge_image(client: TestClient) -> None:
    response = client.post(
        "/api/upscale",
        files={"file": ("art.png", png_bytes(1200), "image/png")},  # 1.44 MP > 1 MP cap
    )
    assert response.status_code == 422
    assert "MP" in response.json()["detail"]


def test_upscale_rejects_garbage_file(client: TestClient) -> None:
    response = client.post(
        "/api/upscale", files={"file": ("x.bin", b"not media", "application/octet-stream")}
    )
    assert response.status_code == 422


def test_upscale_rejects_unplayable_video(client: TestClient) -> None:
    fake_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
    response = client.post("/api/upscale", files={"file": ("clip.mp4", fake_mp4, "video/mp4")})
    assert response.status_code == 422
    # either ffmpeg rejects it as unplayable, or a bare CI box has no ffmpeg at all
    assert "playable" in response.json()["detail"] or "ffmpeg" in response.json()["detail"].lower()


# ---- processor -------------------------------------------------------------------


class FakeUpscale(ManagedPipeline):
    def __init__(self) -> None:
        super().__init__("upscale", vram_estimate_gb=1, vram_peak_gb=6, offload_policy="cpu")
        self.calls: list[dict] = []

    def load(self) -> None: ...
    def to_gpu(self) -> None: ...
    def to_cpu(self) -> None: ...
    def unload(self) -> None: ...

    def upscale_image(self, src, dst, *, variant, scale):
        assert Path(src).is_file()
        self.calls.append({"src": Path(src).name, "variant": variant, "scale": scale})
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"UPSCALED")
        return dst


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
    )


def make_upscale_job(settings: Settings, media: str, extension: str) -> Job:
    job_id = new_job_id()
    media_path = settings.outputs_dir / job_id / "inputs" / f"source{extension}"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"MEDIA")
    return Job(
        id=job_id,
        kind=JobKind.UPSCALE,
        params=UpscaleParams(
            media_path=media_path, media=media, variant="anime", scale=2
        ),
        label="source · 2x",
    )


async def test_processor_image(settings: Settings) -> None:
    pipe = FakeUpscale()
    processor = UpscaleProcessor(build_manager(pipe), settings)
    job = make_upscale_job(settings, "image", ".png")

    outputs = await processor.process(job, ProgressLog())

    assert outputs == {"image": f"/outputs/{job.id}/output.png"}
    assert (settings.outputs_dir / job.id / "output.png").read_bytes() == b"UPSCALED"
    assert pipe.calls == [{"src": "source.png", "variant": "anime", "scale": 2}]


async def test_processor_video(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = FakeUpscale()
    processor = UpscaleProcessor(build_manager(pipe), settings)
    job = make_upscale_job(settings, "video", ".mp4")
    job_dir = settings.outputs_dir / job.id

    async def fake_probe_fps(src):
        return 24.0

    async def fake_extract_frames(src, frames_dir):
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames = [frames_dir / f"frame_{i:06d}.png" for i in range(1, 4)]
        for frame in frames:
            frame.write_bytes(b"FRAME")
        return frames

    async def fake_frames_to_video(frames_dir, dst, *, fps, audio_src=None):
        assert fps == 24.0
        assert audio_src is not None
        # every upscaled frame must exist before assembly
        assert len(list(frames_dir.glob("frame_*.png"))) == 3
        dst.write_bytes(b"FINAL")
        return dst

    monkeypatch.setattr(upscale_module.ffmpeg, "probe_fps", fake_probe_fps)
    monkeypatch.setattr(upscale_module.ffmpeg, "extract_frames", fake_extract_frames)
    monkeypatch.setattr(upscale_module.ffmpeg, "frames_to_video", fake_frames_to_video)

    progress = ProgressLog()
    outputs = await processor.process(job, progress)

    assert outputs == {"video": f"/outputs/{job.id}/output.mp4"}
    assert len(pipe.calls) == 3
    # frame intermediates are cleaned up
    assert not (job_dir / "frames").exists()
    assert not (job_dir / "frames_up").exists()
    assert "encoding" in progress.stages()


# ---- ffmpeg frame round-trip (needs a real ffmpeg) -----------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_ffmpeg_frame_roundtrip(tmp_path: Path) -> None:
    from tests.test_ffmpeg import make_test_video

    src = tmp_path / "clip.mp4"
    make_test_video(src, seconds=0.5)

    fps = await ffmpeg.probe_fps(src)
    assert fps > 0

    frames = await ffmpeg.extract_frames(src, tmp_path / "frames")
    assert len(frames) >= int(0.5 * fps) - 1

    out = await ffmpeg.frames_to_video(
        tmp_path / "frames", tmp_path / "out.mp4", fps=fps, audio_src=src
    )
    assert out.is_file()
    duration = await ffmpeg.probe_duration(out)
    assert duration == pytest.approx(0.5, abs=0.2)
