"""POST /api/talking-head, /api/broll and /api/full-video: validation, input
saving, enqueueing."""

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from tests.test_voices import entry, write_voices_json, write_wav


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path):
    assets = tmp_path / "assets"
    write_wav(assets / "voices" / "en-test.wav")
    write_voices_json(assets, [entry()])
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=assets,
        max_script_chars=200,
        max_prompt_chars=100,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def post_talking_head(client: TestClient, **overrides):
    data = {"script": "Hello there, this is a test.", "voice": "en-test"}
    data.update({k: v for k, v in overrides.items() if k in ("script", "voice")})
    files = {"avatar": overrides.get("avatar", ("avatar.png", png_bytes(), "image/png"))}
    return client.post("/api/talking-head", data=data, files=files)


def test_talking_head_accepts_and_queues(client: TestClient, tmp_path: Path) -> None:
    response = post_talking_head(client)
    assert response.status_code == 200
    job_id = response.json()["jobId"]

    # avatar saved under the job's inputs folder
    saved = tmp_path / "outputs" / job_id / "inputs" / "avatar.png"
    assert saved.is_file()

    # job is known to the API immediately
    status = client.get(f"/api/status/{job_id}").json()
    assert status["status"] in ("queued", "processing", "failed")


def test_talking_head_rejects_unknown_voice(client: TestClient) -> None:
    response = post_talking_head(client, voice="nonexistent")
    assert response.status_code == 422
    assert "unknown voice" in response.json()["detail"]


def test_talking_head_rejects_long_script(client: TestClient) -> None:
    response = post_talking_head(client, script="x" * 201)
    assert response.status_code == 422
    assert "too long" in response.json()["detail"]


def test_talking_head_rejects_empty_script(client: TestClient) -> None:
    response = post_talking_head(client, script="   ")
    assert response.status_code == 422


def test_talking_head_rejects_non_image_avatar(client: TestClient) -> None:
    response = post_talking_head(client, avatar=("a.png", b"not an image", "image/png"))
    assert response.status_code == 422
    assert "not a valid image" in response.json()["detail"]


def test_broll_accepts_without_image(client: TestClient) -> None:
    response = client.post("/api/broll", data={"prompt": "a foggy harbour", "duration": 4})
    assert response.status_code == 200
    assert "jobId" in response.json()


def test_broll_accepts_with_reference_image(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/broll",
        data={"prompt": "a foggy harbour", "duration": 3},
        files={"image": ("ref.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    assert (tmp_path / "outputs" / job_id / "inputs" / "reference.png").is_file()


@pytest.mark.parametrize("duration", [2, 6, "abc"])
def test_broll_rejects_bad_duration(client: TestClient, duration) -> None:
    response = client.post("/api/broll", data={"prompt": "ok", "duration": duration})
    assert response.status_code == 422


def test_broll_rejects_long_prompt(client: TestClient) -> None:
    response = client.post("/api/broll", data={"prompt": "x" * 101, "duration": 3})
    assert response.status_code == 422


# ---- POST /api/full-video --------------------------------------------------------

TAGGED_SCRIPT = (
    "Welcome to the channel. [BROLL: aerial harbour shot] Ships arrive every "
    "morning. [ONCAMERA] Thanks for watching."
)


@pytest.fixture
def fv_client(tmp_path: Path):
    """Full-video client with a tiny segment cap so the limit is testable."""
    assets = tmp_path / "assets"
    write_wav(assets / "voices" / "en-test.wav")
    write_voices_json(assets, [entry()])
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=assets,
        full_video_max_segments=3,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def post_full_video(client: TestClient, *, script: str = TAGGED_SCRIPT,
                    voice: str = "en-test", avatar: bool = True, clips=()):
    files = []
    if avatar:
        files.append(("avatar", ("avatar.png", png_bytes(), "image/png")))
    for name, payload in clips:
        files.append(("clips", (name, payload, "video/mp4")))
    return client.post(
        "/api/full-video",
        data={"script": script, "voice": voice},
        files=files or None,
    )


def test_full_video_accepts_and_queues(fv_client: TestClient, tmp_path: Path) -> None:
    response = post_full_video(fv_client)
    assert response.status_code == 200
    job_id = response.json()["jobId"]

    assert (tmp_path / "outputs" / job_id / "inputs" / "avatar.png").is_file()
    status = fv_client.get(f"/api/status/{job_id}").json()
    assert status["status"] in ("queued", "processing", "failed")

    jobs = fv_client.get("/api/jobs?kind=full_video").json()["jobs"]
    assert any(j["jobId"] == job_id for j in jobs)


def test_full_video_all_broll_needs_no_avatar(fv_client: TestClient) -> None:
    response = post_full_video(
        fv_client, script="[BROLL: dunes] Sand as far as the eye can see.", avatar=False
    )
    assert response.status_code == 200


def test_full_video_rejects_missing_avatar_with_oncamera_text(fv_client: TestClient) -> None:
    response = post_full_video(fv_client, avatar=False)
    assert response.status_code == 422
    assert "avatar image is required" in response.json()["detail"]


def test_full_video_rejects_unknown_marker(fv_client: TestClient) -> None:
    response = post_full_video(fv_client, script="Hi. [CHART: sales] More text.")
    assert response.status_code == 422
    assert "unknown visual marker" in response.json()["detail"]


def test_full_video_rejects_empty_marker_prompt(fv_client: TestClient) -> None:
    response = post_full_video(fv_client, script="Hi. [BROLL: ] More text.")
    assert response.status_code == 422
    assert "needs a value" in response.json()["detail"]


def test_full_video_rejects_too_many_segments(fv_client: TestClient) -> None:
    script = "Intro. " + " ".join(
        f"[BROLL: scene {i}] Narration {i}." for i in range(4)
    )
    response = post_full_video(fv_client, script=script)
    assert response.status_code == 422
    assert "maximum is 3" in response.json()["detail"]


def test_full_video_rejects_missing_referenced_clip(fv_client: TestClient) -> None:
    response = post_full_video(
        fv_client, script="[CLIP: tour.mp4] Our warehouse.", avatar=False
    )
    assert response.status_code == 422
    assert "tour.mp4" in response.json()["detail"]


def test_full_video_rejects_garbage_clip_bytes(fv_client: TestClient) -> None:
    response = post_full_video(
        fv_client,
        script="[CLIP: tour.mp4] Our warehouse.",
        avatar=False,
        clips=[("tour.mp4", b"definitely not a video file")],
    )
    assert response.status_code == 422
    assert "MP4, MOV or WebM" in response.json()["detail"]


def test_full_video_rejects_duplicate_clip_uploads(fv_client: TestClient) -> None:
    response = post_full_video(
        fv_client,
        script="[CLIP: tour.mp4] Our warehouse.",
        avatar=False,
        clips=[("tour.mp4", b"x" * 16), ("TOUR.MP4", b"y" * 16)],
    )
    assert response.status_code == 422
    assert "duplicate clip upload" in response.json()["detail"]


def test_full_video_rejects_unknown_voice(fv_client: TestClient) -> None:
    response = post_full_video(fv_client, voice="nonexistent")
    assert response.status_code == 422
    assert "unknown voice" in response.json()["detail"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_full_video_accepts_playable_clip(fv_client: TestClient, tmp_path: Path) -> None:
    from tests.test_ffmpeg import make_test_video

    clip_src = tmp_path / "real.mp4"
    make_test_video(clip_src, seconds=1.0)

    response = post_full_video(
        fv_client,
        script="[CLIP: Tour.mp4] Our warehouse in the fog.",
        avatar=False,
        clips=[("Tour.mp4", clip_src.read_bytes())],
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    assert (tmp_path / "outputs" / job_id / "inputs" / "clip_0.mp4").is_file()


# ---- POST /api/lora-training and the `lora` field --------------------------------


def post_lora_training(client: TestClient, *, image_count: int = 5, **overrides):
    data = {"name": "Ink Sketch", "trigger": "1nk_style"}
    data.update(overrides)
    files = [
        ("images", (f"img_{i}.png", png_bytes(), "image/png")) for i in range(image_count)
    ]
    return client.post("/api/lora-training", data=data, files=files)


def install_test_style(tmp_path: Path):
    from app.services.loras import LoraRegistry

    weights = tmp_path / "trained.safetensors"
    weights.write_bytes(b"LORA")
    registry = LoraRegistry(tmp_path / "models" / "loras")
    return registry.install(weights, name="Ink Sketch", trigger="1nk_style")


def test_lora_training_accepts_and_queues(client: TestClient, tmp_path: Path) -> None:
    response = post_lora_training(client)
    assert response.status_code == 200
    job_id = response.json()["jobId"]

    dataset = tmp_path / "outputs" / job_id / "inputs" / "dataset"
    assert len(list(dataset.glob("img_*.png"))) == 5

    jobs = client.get("/api/jobs?kind=lora_training").json()["jobs"]
    assert any(j["jobId"] == job_id for j in jobs)


def test_lora_training_rejects_too_few_images(client: TestClient) -> None:
    response = post_lora_training(client, image_count=2)
    assert response.status_code == 422
    assert "at least 5 training images" in response.json()["detail"]


def test_lora_training_rejects_bad_trigger(client: TestClient) -> None:
    for trigger in ("x", "two words", "hy-phen", "a" * 31):
        response = post_lora_training(client, trigger=trigger)
        assert response.status_code == 422, trigger
        assert "trigger must be" in response.json()["detail"]


def test_lora_training_rejects_too_many_steps(client: TestClient) -> None:
    response = post_lora_training(client, steps="99999")
    assert response.status_code == 422
    assert "steps must be at most" in response.json()["detail"]


def test_lora_training_rejects_non_image(client: TestClient) -> None:
    files = [("images", (f"img_{i}.png", png_bytes(), "image/png")) for i in range(4)]
    files.append(("images", ("bad.png", b"not an image", "image/png")))
    response = client.post(
        "/api/lora-training", data={"name": "S", "trigger": "1nk_style"}, files=files
    )
    assert response.status_code == 422
    assert "not a valid image" in response.json()["detail"]


def test_image_rejects_unknown_style(client: TestClient) -> None:
    response = client.post(
        "/api/image", data={"prompt": "a harbour", "lora": "no-such-style"}
    )
    assert response.status_code == 422
    assert "unknown style" in response.json()["detail"]


def test_image_style_prepends_trigger(client: TestClient, tmp_path: Path) -> None:
    style = install_test_style(tmp_path)
    response = client.post(
        "/api/image", data={"prompt": "a harbour at dawn", "lora": style.id}
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]

    jobs = client.get("/api/jobs?kind=image").json()["jobs"]
    label = next(j["label"] for j in jobs if j["jobId"] == job_id)
    assert label.startswith("1nk_style, a harbour at dawn")


def test_broll_style_not_applicable_to_other_models(client: TestClient, tmp_path: Path) -> None:
    style = install_test_style(tmp_path)
    response = client.post(
        "/api/image",
        data={"prompt": "a harbour", "lora": style.id, "model": "flux-schnell"},
    )
    assert response.status_code == 422
    assert "cannot be applied" in response.json()["detail"]


# ---- reference-image editing (flux-kontext) --------------------------------------


def test_image_kontext_requires_reference(client: TestClient) -> None:
    response = client.post(
        "/api/image", data={"prompt": "show him from behind", "model": "flux-kontext"}
    )
    assert response.status_code == 422
    assert "reference image" in response.json()["detail"]


def test_image_reference_rejected_on_other_engines(client: TestClient) -> None:
    response = client.post(
        "/api/image",
        data={"prompt": "a harbour", "model": "wan-5b"},
        files={"image": ("ref.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 422
    assert "Kontext" in response.json()["detail"]


def test_image_kontext_accepts_reference(client: TestClient) -> None:
    response = client.post(
        "/api/image",
        data={"prompt": "show him from behind", "model": "flux-kontext", "guidance": "1.8"},
        files={"image": ("ref.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]

    jobs = client.get("/api/jobs?kind=image").json()["jobs"]
    assert any(job["jobId"] == job_id for job in jobs)


def test_broll_accepts_style(client: TestClient, tmp_path: Path) -> None:
    style = install_test_style(tmp_path)
    response = client.post(
        "/api/broll",
        data={"prompt": "1nk_style, the character waves", "duration": 3, "lora": style.id},
    )
    assert response.status_code == 200
    # trigger already present — not duplicated
    jobs = client.get("/api/jobs?kind=broll").json()["jobs"]
    label = jobs[0]["label"]
    assert label.count("1nk_style") == 1


def test_submitted_job_fails_gracefully_without_models(client: TestClient) -> None:
    """On this dev machine there is no torch/fish-speech: the job must fail with a
    clear error while the server stays healthy — never hang or crash."""
    import time

    response = post_talking_head(client)
    job_id = response.json()["jobId"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/status/{job_id}").json()
        if body["status"] == "failed":
            assert body["error"]  # a message, not a blank
            break
        time.sleep(0.05)
    else:
        raise AssertionError("job never reached a terminal state")

    assert client.get("/health").json() == {"status": "ok"}
