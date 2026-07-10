"""VoiceRegistry loading/validation and the /api/voices endpoint."""

import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.voices import VoiceRegistry


def write_wav(path: Path, seconds: float = 15.0, rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(seconds * rate))


def write_voices_json(assets_dir: Path, entries: list[dict]) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "voices.json").write_text(json.dumps(entries), encoding="utf-8")


def entry(voice_id: str = "en-test", ref: str = "voices/en-test.wav") -> dict:
    return {"id": voice_id, "name": "Test Voice", "language": "en", "ref_audio": ref}


def test_loads_valid_voice(tmp_path: Path) -> None:
    write_wav(tmp_path / "voices" / "en-test.wav")
    write_voices_json(tmp_path, [entry()])

    registry = VoiceRegistry(tmp_path)
    registry.load()

    voice = registry.get("en-test")
    assert voice is not None
    assert voice.name == "Test Voice"
    assert voice.ref_audio.is_file()
    assert len(registry.voices) == 1


def test_skips_voice_with_missing_clip(tmp_path: Path) -> None:
    write_wav(tmp_path / "voices" / "exists.wav")
    write_voices_json(
        tmp_path,
        [entry("ok", "voices/exists.wav"), entry("broken", "voices/missing.wav")],
    )

    registry = VoiceRegistry(tmp_path)
    registry.load()

    assert registry.get("ok") is not None
    assert registry.get("broken") is None


def test_skips_duplicate_ids_and_malformed_entries(tmp_path: Path) -> None:
    write_wav(tmp_path / "voices" / "a.wav")
    write_voices_json(
        tmp_path,
        [
            entry("dup", "voices/a.wav"),
            entry("dup", "voices/a.wav"),
            {"id": "no-fields"},
            "not even a dict",
        ],
    )

    registry = VoiceRegistry(tmp_path)
    registry.load()

    assert len(registry.voices) == 1
    assert registry.get("dup") is not None


def test_bad_json_yields_empty_registry_not_crash(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "voices.json").write_text("{broken", encoding="utf-8")

    registry = VoiceRegistry(tmp_path)
    registry.load()
    assert registry.voices == []


def test_missing_file_yields_empty_registry(tmp_path: Path) -> None:
    registry = VoiceRegistry(tmp_path / "nowhere")
    registry.load()
    assert registry.voices == []


def test_short_clip_loads_with_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_wav(tmp_path / "voices" / "short.wav", seconds=1.0)
    write_voices_json(tmp_path, [entry("short", "voices/short.wav")])

    registry = VoiceRegistry(tmp_path)
    with caplog.at_level("WARNING"):
        registry.load()

    assert registry.get("short") is not None  # warned, not rejected
    assert any("recommended" in record.message for record in caplog.records)


# ---- API ------------------------------------------------------------------------


def test_api_voices_returns_presets_without_ref_audio(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    write_wav(assets / "voices" / "en-test.wav")
    write_voices_json(assets, [entry()])

    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=assets,
    )
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/voices").json()

    assert body == {
        "voices": [{"id": "en-test", "name": "Test Voice", "language": "en"}]
    }
    # the reference clip path must never leave the backend
    assert "ref_audio" not in json.dumps(body)
