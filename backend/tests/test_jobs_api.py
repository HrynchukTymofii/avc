"""Library actions: GET /api/jobs/{id}, regenerate, delete, upscale-from-job,
and params surviving the status.json snapshot round-trip."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.queue.job import (
    FullVideoParams,
    Job,
    JobState,
    new_job_id,
)
from app.queue.job_store import JobStore
from app.schemas import JobKind
from tests.conftest import make_job


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


# ---- params persistence -------------------------------------------------------


def test_params_survive_snapshot_roundtrip(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = Job(
        id=new_job_id(),
        kind=JobKind.FULL_VIDEO,
        params=FullVideoParams(
            script="[BROLL: a harbour] Some narration.",
            voice_id="en-test",
            avatar_path=tmp_path / "a" / "inputs" / "avatar.png",
            orientation="portrait",
            clip_paths={"intro.mp4": tmp_path / "a" / "inputs" / "clip_0.mp4"},
        ),
        label="a full video",
        cost=12,
    )
    store.add(job)

    fresh = JobStore(tmp_path)
    fresh.rehydrate()
    restored = fresh.get(job.id)
    assert restored is not None
    assert restored.params == job.params
    assert restored.cost == 12


def test_old_snapshots_without_params_still_load(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = make_job("legacy")
    job.params = None
    store.add(job)

    fresh = JobStore(tmp_path)
    fresh.rehydrate()
    restored = fresh.get(job.id)
    assert restored is not None
    assert restored.params is None


# ---- detail -------------------------------------------------------------------


def test_job_detail_shape(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job("a test prompt")
    store.add(job)

    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["jobId"] == job.id
    assert body["kind"] == "broll"
    assert body["status"] == "queued"
    assert body["model"] == "wan-5b"
    assert body["prompt"] == "a test prompt"
    assert body["canRegenerate"] is True
    assert body["canUpscale"] is False

    store.update(
        job.id,
        state=JobState.FINISHED,
        outputs={"video": f"/outputs/{job.id}/output.mp4"},
    )
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["status"] == "finished"
    assert body["video"] == f"/outputs/{job.id}/output.mp4"
    assert body["canUpscale"] is True


def test_job_detail_unknown_404(client: TestClient) -> None:
    assert client.get("/api/jobs/no-such-job").status_code == 404


# ---- regenerate ---------------------------------------------------------------


def test_regenerate_copies_inputs_and_queues(client: TestClient, tmp_path: Path) -> None:
    created = client.post(
        "/api/broll",
        data={"prompt": "a foggy harbour", "duration": 4},
        files={"image": ("ref.png", png_bytes(), "image/png")},
    )
    assert created.status_code == 200
    source_id = created.json()["jobId"]

    response = client.post(f"/api/jobs/{source_id}/regenerate")
    assert response.status_code == 200
    new_id = response.json()["jobId"]
    assert new_id != source_id

    store = client.app.state.store
    new_job = store.get(new_id)
    assert new_job is not None
    assert new_job.params.prompt == "a foggy harbour"
    # the reference image was copied into the new job's own inputs dir
    assert new_job.params.image_path.is_file()
    assert str(new_id) in str(new_job.params.image_path)


def test_regenerate_without_saved_params_409(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job("legacy")
    job.params = None
    store.add(job)

    response = client.post(f"/api/jobs/{job.id}/regenerate")
    assert response.status_code == 409
    assert "settings weren't saved" in response.json()["detail"]


# ---- delete -------------------------------------------------------------------


def test_delete_hides_job_and_removes_files(client: TestClient, tmp_path: Path) -> None:
    store = client.app.state.store
    job = make_job("to delete")
    job.cost = 8
    store.add(job)
    job_dir = tmp_path / "outputs" / job.id
    (job_dir / "output.mp4").write_bytes(b"fake video")
    store.update(
        job.id,
        state=JobState.FINISHED,
        outputs={"video": f"/outputs/{job.id}/output.mp4"},
    )

    assert client.delete(f"/api/jobs/{job.id}").status_code == 204

    # gone from every read path…
    assert client.get(f"/api/jobs/{job.id}").status_code == 404
    assert client.get(f"/api/status/{job.id}").status_code == 404
    assert job.id not in {j["jobId"] for j in client.get("/api/jobs").json()["jobs"]}
    # …files removed, but the snapshot (the spend record) is kept
    assert not (job_dir / "output.mp4").exists()
    assert (job_dir / "status.json").is_file()
    assert store.credits_spent(job.user_id) == 8


def test_delete_running_job_409(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job("still running")
    store.add(job)
    store.update(job.id, state=JobState.PROCESSING)

    response = client.delete(f"/api/jobs/{job.id}")
    assert response.status_code == 409


# ---- upscale from a source job ------------------------------------------------


def test_upscale_from_source_job(client: TestClient, tmp_path: Path) -> None:
    store = client.app.state.store
    job = make_job("a generated image", kind=JobKind.IMAGE)
    store.add(job)
    job_dir = tmp_path / "outputs" / job.id
    (job_dir / "output.png").write_bytes(png_bytes())
    store.update(
        job.id,
        state=JobState.FINISHED,
        outputs={"image": f"/outputs/{job.id}/output.png"},
    )

    response = client.post("/api/upscale", data={"source_job": job.id})
    assert response.status_code == 200
    upscale_id = response.json()["jobId"]

    new_job = store.get(upscale_id)
    assert new_job is not None
    assert new_job.params.media == "image"
    assert new_job.params.media_path.is_file()


def test_upscale_from_unfinished_source_422(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job("still queued")
    store.add(job)

    response = client.post("/api/upscale", data={"source_job": job.id})
    assert response.status_code == 422


def test_upscale_without_file_or_source_422(client: TestClient) -> None:
    response = client.post("/api/upscale", data={})
    assert response.status_code == 422
