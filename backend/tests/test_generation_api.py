"""POST /api/talking-head and /api/broll: validation, input saving, enqueueing."""

import io
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
