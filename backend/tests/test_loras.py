"""LoraRegistry disk format and the /api/loras routes."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.loras import LoraRegistry


@pytest.fixture
def registry(tmp_path: Path) -> LoraRegistry:
    return LoraRegistry(tmp_path / "loras")


def install_style(registry: LoraRegistry, tmp_path: Path, name: str = "Ink Sketch"):
    weights = tmp_path / "trained.safetensors"
    weights.write_bytes(b"LORA")
    return registry.install(
        weights, name=name, trigger="1nk_style", steps=2000, image_count=30
    )


def test_install_list_get_roundtrip(registry: LoraRegistry, tmp_path: Path) -> None:
    info = install_style(registry, tmp_path)
    assert info.id.startswith("ink-sketch-")
    assert info.weights_path.read_bytes() == b"LORA"

    listed = registry.list()
    assert [s.id for s in listed] == [info.id]
    fetched = registry.get(info.id)
    assert fetched is not None
    assert fetched.name == "Ink Sketch"
    assert fetched.trigger == "1nk_style"
    assert fetched.base == "wan-5b"


def test_delete(registry: LoraRegistry, tmp_path: Path) -> None:
    info = install_style(registry, tmp_path)
    assert registry.delete(info.id)
    assert registry.get(info.id) is None
    assert registry.list() == []
    assert not registry.delete(info.id)  # second delete is a no-op


def test_get_rejects_path_tricks(registry: LoraRegistry, tmp_path: Path) -> None:
    install_style(registry, tmp_path)
    assert registry.get("../outside") is None
    assert registry.get("") is None


def test_unreadable_metadata_is_skipped(registry: LoraRegistry, tmp_path: Path) -> None:
    info = install_style(registry, tmp_path)
    broken = tmp_path / "loras" / "broken-style"
    broken.mkdir()
    (broken / "lora.safetensors").write_bytes(b"LORA")
    (broken / "lora.json").write_text("not json", encoding="utf-8")
    assert [s.id for s in registry.list()] == [info.id]


def test_missing_weights_is_skipped(registry: LoraRegistry, tmp_path: Path) -> None:
    info = install_style(registry, tmp_path)
    (tmp_path / "loras" / info.id / "lora.safetensors").unlink()
    assert registry.list() == []


# ---- routes -----------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client, settings


def test_loras_endpoint_lists_styles(client, tmp_path: Path) -> None:
    test_client, settings = client
    registry = LoraRegistry(settings.loras_dir)
    info = install_style(registry, tmp_path)

    body = test_client.get("/api/loras").json()
    assert len(body["loras"]) == 1
    style = body["loras"][0]
    assert style["id"] == info.id
    assert style["name"] == "Ink Sketch"
    assert style["trigger"] == "1nk_style"
    assert style["base"] == "wan-5b"
    assert style["createdAt"].startswith(info.created_at.date().isoformat())


def test_delete_endpoint(client, tmp_path: Path) -> None:
    test_client, settings = client
    registry = LoraRegistry(settings.loras_dir)
    info = install_style(registry, tmp_path)

    assert test_client.delete(f"/api/loras/{info.id}").status_code == 204
    assert test_client.get("/api/loras").json() == {"loras": []}
    assert test_client.delete(f"/api/loras/{info.id}").status_code == 404
