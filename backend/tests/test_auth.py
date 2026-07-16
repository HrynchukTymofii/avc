"""Bearer-token auth: token verification, the approval gate, and owner scoping.

The rest of the suite runs with AUTH_ENABLED=false (the default) and is
untouched by auth; these tests build a client with auth enabled.
"""

import io
import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

SECRET = "test-secret-0123456789abcdef0123456789abcdef"


def make_token(
    user_id: str = "user-1",
    *,
    approved: bool = True,
    role: str = "user",
    expires_in: int = 600,
    secret: str = SECRET,
) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@example.com",
            "name": user_id,
            "approved": approved,
            "role": role,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in,
        },
        secret,
        algorithm="HS256",
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        auth_enabled=True,
        api_jwt_secret=SECRET,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def submit_image(client: TestClient, headers: dict[str, str] | None = None):
    return client.post("/api/image", data={"prompt": "a harbour"}, headers=headers)


# ---- token verification -------------------------------------------------------------


def test_requests_without_token_are_rejected(client: TestClient) -> None:
    assert submit_image(client).status_code == 401
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/models").status_code == 401
    assert client.get("/api/voices").status_code == 401
    assert client.get("/api/loras").status_code == 401
    # health stays open for the container healthcheck
    assert client.get("/health").status_code == 200


def test_garbage_token_is_rejected(client: TestClient) -> None:
    assert submit_image(client, bearer("not-a-jwt")).status_code == 401


def test_wrong_secret_is_rejected(client: TestClient) -> None:
    token = make_token(secret="some-other-secret-0123456789abcdef012345")
    assert submit_image(client, bearer(token)).status_code == 401


def test_expired_token_is_rejected(client: TestClient) -> None:
    token = make_token(expires_in=-60)
    assert submit_image(client, bearer(token)).status_code == 401


def test_valid_token_is_accepted(client: TestClient) -> None:
    response = submit_image(client, bearer(make_token()))
    assert response.status_code == 200
    assert "jobId" in response.json()


# ---- approval gate --------------------------------------------------------------------


def test_unapproved_user_cannot_submit_but_can_browse(client: TestClient) -> None:
    headers = bearer(make_token(approved=False))
    response = submit_image(client, headers)
    assert response.status_code == 403
    assert "awaiting approval" in response.json()["detail"]

    # read-only endpoints still work — the UI can render and show the banner
    assert client.get("/api/models", headers=headers).status_code == 200
    assert client.get("/api/jobs", headers=headers).status_code == 200


# ---- owner scoping ---------------------------------------------------------------------


def test_jobs_and_status_are_owner_scoped(client: TestClient) -> None:
    alice, bob = bearer(make_token("alice")), bearer(make_token("bob"))

    job_id = submit_image(client, alice).json()["jobId"]

    # Alice sees her job; Bob sees an empty list and a 404 on direct access.
    alice_jobs = client.get("/api/jobs", headers=alice).json()["jobs"]
    assert [j["jobId"] for j in alice_jobs] == [job_id]
    assert client.get("/api/jobs", headers=bob).json()["jobs"] == []
    assert client.get(f"/api/status/{job_id}", headers=bob).status_code == 404
    assert client.get(f"/api/status/{job_id}", headers=alice).status_code == 200


def test_admin_sees_all_jobs(client: TestClient) -> None:
    alice = bearer(make_token("alice"))
    admin = bearer(make_token("admin-user", role="admin"))

    job_id = submit_image(client, alice).json()["jobId"]

    admin_jobs = client.get("/api/jobs", headers=admin).json()["jobs"]
    assert job_id in [j["jobId"] for j in admin_jobs]
    assert client.get(f"/api/status/{job_id}", headers=admin).status_code == 200


def test_user_id_survives_restart(client: TestClient, tmp_path: Path) -> None:
    from app.queue.job_store import JobStore

    alice = bearer(make_token("alice"))
    job_id = submit_image(client, alice).json()["jobId"]

    store = JobStore(tmp_path / "outputs")
    store.rehydrate()
    job = store.get(job_id)
    assert job is not None
    assert job.user_id == "alice"
