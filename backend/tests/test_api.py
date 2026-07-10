"""HTTP layer: /api/status/{jobId} and /api/jobs against a real app instance."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.queue.job import JobState
from app.schemas import JobKind
from tests.conftest import make_job


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


def test_status_unknown_job_404(client: TestClient) -> None:
    response = client.get("/api/status/no-such-job")
    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_status_queued_reports_position(client: TestClient) -> None:
    store = client.app.state.store
    first, second = make_job("first"), make_job("second")
    store.add(first)
    store.add(second)

    assert client.get(f"/api/status/{first.id}").json() == {"status": "queued", "position": 1}
    assert client.get(f"/api/status/{second.id}").json() == {"status": "queued", "position": 2}


def test_status_processing_shape(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job()
    store.add(job)
    store.update(job.id, state=JobState.PROCESSING, progress=62, stage="lip-sync")

    assert client.get(f"/api/status/{job.id}").json() == {
        "status": "processing",
        "progress": 62,
        "stage": "lip-sync",
    }


def test_status_finished_broll_omits_audio(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job()
    store.add(job)
    store.update(
        job.id,
        state=JobState.FINISHED,
        outputs={"video": f"/outputs/{job.id}/output.mp4"},
    )

    body = client.get(f"/api/status/{job.id}").json()
    assert body == {"status": "finished", "video": f"/outputs/{job.id}/output.mp4"}
    assert "audio" not in body


def test_status_finished_talking_head_includes_audio(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job(kind=JobKind.TALKING_HEAD)
    store.add(job)
    store.update(
        job.id,
        state=JobState.FINISHED,
        outputs={
            "video": f"/outputs/{job.id}/output.mp4",
            "audio": f"/outputs/{job.id}/speech.wav",
        },
    )

    body = client.get(f"/api/status/{job.id}").json()
    assert body["status"] == "finished"
    assert body["audio"] == f"/outputs/{job.id}/speech.wav"


def test_status_failed(client: TestClient) -> None:
    store = client.app.state.store
    job = make_job()
    store.add(job)
    store.update(job.id, state=JobState.FAILED, error="CUDA out of memory")

    assert client.get(f"/api/status/{job.id}").json() == {
        "status": "failed",
        "error": "CUDA out of memory",
    }


def test_jobs_list_shape_filter_and_limit(client: TestClient) -> None:
    store = client.app.state.store
    broll = make_job("a broll clip")
    talking = make_job("a talking head", kind=JobKind.TALKING_HEAD)
    store.add(broll)
    store.add(talking)
    store.update(broll.id, state=JobState.FINISHED, outputs={"video": "/outputs/b/output.mp4"})

    body = client.get("/api/jobs").json()
    assert {j["jobId"] for j in body["jobs"]} == {broll.id, talking.id}

    finished_entry = next(j for j in body["jobs"] if j["jobId"] == broll.id)
    assert finished_entry["status"] == "finished"
    assert finished_entry["kind"] == "broll"
    assert finished_entry["label"] == "a broll clip"
    assert finished_entry["video"] == "/outputs/b/output.mp4"
    assert "createdAt" in finished_entry

    queued_entry = next(j for j in body["jobs"] if j["jobId"] == talking.id)
    assert queued_entry["status"] == "queued"
    assert "video" not in queued_entry  # exclude_none keeps the payload clean

    filtered = client.get("/api/jobs", params={"kind": "talking_head"}).json()
    assert [j["jobId"] for j in filtered["jobs"]] == [talking.id]

    limited = client.get("/api/jobs", params={"limit": 1}).json()
    assert len(limited["jobs"]) == 1


def test_submitted_job_flows_through_worker_to_api(client: TestClient) -> None:
    """End-to-end through the real app loop: submit → worker picks it up → the
    processor fails (no torch/models on this dev machine) → the status endpoint
    reports the failure gracefully and the worker survives."""
    import time

    app = client.app
    job = make_job("integration")
    # TestClient runs the app's event loop in a background thread; portal.call
    # executes the async submit on that loop.
    client.portal.call(app.state.worker.submit, job)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/status/{job.id}").json()
        if body["status"] in ("finished", "failed"):
            assert body["status"] == "failed"
            assert body["error"]  # clear message, never blank
            return
        time.sleep(0.05)
    raise AssertionError("job never reached a terminal state")
