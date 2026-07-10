"""Voice presets for S2 Pro voice cloning.

Voices are defined in assets/voices.json; each entry points at a 10-30 second
reference WAV under assets/voices/. The registry validates entries at startup
and skips broken ones with a warning rather than failing the whole app — a
missing clip disables that one voice, nothing else.
"""

from __future__ import annotations

import json
import logging
import wave
from pathlib import Path

from app.schemas import Voice

log = logging.getLogger(__name__)

_VOICES_FILE = "voices.json"
_RECOMMENDED_MIN_S = 5.0
_RECOMMENDED_MAX_S = 60.0


class VoiceRegistry:
    def __init__(self, assets_dir: Path) -> None:
        self._assets_dir = assets_dir
        self._voices: dict[str, Voice] = {}

    def load(self) -> None:
        self._voices = {}
        voices_path = self._assets_dir / _VOICES_FILE
        if not voices_path.is_file():
            log.warning(
                "voices.json not found — talking-head generation will have no voices",
                extra={"path": str(voices_path)},
            )
            return

        try:
            entries = json.loads(voices_path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise ValueError("voices.json must contain a JSON array")
        except Exception:
            log.exception("failed to parse voices.json", extra={"path": str(voices_path)})
            return

        for entry in entries:
            voice = self._validate_entry(entry)
            if voice is not None:
                self._voices[voice.id] = voice

        log.info(
            "voice registry loaded",
            extra={"voices": len(self._voices), "ids": sorted(self._voices)},
        )
        if not self._voices:
            log.warning(
                "no usable voices — add reference clips to assets/voices/ and entries "
                "to assets/voices.json (see assets/voices/README.md)"
            )

    def _validate_entry(self, entry: object) -> Voice | None:
        try:
            assert isinstance(entry, dict)
            voice = Voice(
                id=entry["id"],
                name=entry["name"],
                language=entry["language"],
                ref_audio=self._assets_dir / str(entry["ref_audio"]),
                ref_text=entry.get("ref_text"),
            )
        except Exception:
            log.warning("skipping malformed voice entry", extra={"entry": repr(entry)})
            return None

        if voice.id in self._voices:
            log.warning("skipping duplicate voice id", extra={"voice_id": voice.id})
            return None
        if not voice.ref_audio.is_file():
            log.warning(
                "skipping voice with missing reference clip",
                extra={"voice_id": voice.id, "ref_audio": str(voice.ref_audio)},
            )
            return None

        duration = _wav_duration_s(voice.ref_audio)
        if duration is not None and not (_RECOMMENDED_MIN_S <= duration <= _RECOMMENDED_MAX_S):
            log.warning(
                "voice reference clip length is outside the recommended 10-30s range; "
                "cloning quality may suffer",
                extra={"voice_id": voice.id, "duration_s": round(duration, 1)},
            )
        return voice

    @property
    def voices(self) -> list[Voice]:
        return list(self._voices.values())

    def get(self, voice_id: str) -> Voice | None:
        return self._voices.get(voice_id)


def _wav_duration_s(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / rate if rate else None
    except Exception:
        log.warning("could not read WAV header", extra={"path": str(path)})
        return None
