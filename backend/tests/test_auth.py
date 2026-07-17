"""Bearer-token auth: token verification, the credits gate, and owner scoping.

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
    credits: int = 100,
    role: str = "user",
    expires_in: int = 600,
    secret: str = SECRET,
) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@example.com",
            "name": user_id,
            "credits": credits,
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


# ---- credits gate ---------------------------------------------------------------------


def test_out_of_credits_cannot_submit_but_can_browse(client: TestClient) -> None:
    headers = bearer(make_token(credits=0))
    response = submit_image(client, headers)
    assert response.status_code == 403
    assert "Not enough credits" in response.json()["detail"]

    # read-only endpoints still work — the UI can render and show the balance
    assert client.get("/api/models", headers=headers).status_code == 200
    assert client.get("/api/jobs", headers=headers).status_code == 200


def test_credits_endpoint_reports_balance(client: TestClient) -> None:
    headers = bearer(make_token("fresh-user", credits=100))
    assert client.get("/api/credits", headers=headers).json() == {
        "allowance": 100,
        "spent": 0,
        "balance": 100,
        "unlimited": False,
    }


def test_admin_generates_for_free(client: TestClient) -> None:
    headers = bearer(make_token("boss", credits=0, role="admin"))
    assert submit_image(client, headers).status_code == 200
    assert client.get("/api/credits", headers=headers).json()["unlimited"] is True


def test_credits_spent_counts_non_failed_jobs(tmp_path: Path) -> None:
    from app.queue.job import Job, JobState
    from app.queue.job_store import JobStore
    from app.schemas import JobKind

    store = JobStore(tmp_path)
    store.add(Job(id="a", kind=JobKind.IMAGE, params=None, user_id="u", cost=3))
    store.add(Job(id="b", kind=JobKind.BROLL, params=None, user_id="u", cost=8))
    store.add(Job(id="c", kind=JobKind.IMAGE, params=None, user_id="other", cost=5))
    assert store.credits_spent("u") == 11

    # failed jobs are refunded by not being counted
    store.update("b", state=JobState.FAILED)
    assert store.credits_spent("u") == 3


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
