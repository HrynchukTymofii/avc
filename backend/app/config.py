"""Application settings, loaded from environment variables and the project .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

OffloadPolicy = Literal["cpu", "unload"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Project-root .env is shared with docker-compose; a backend-local .env wins if present.
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend_port: int = 8000

    models_dir: Path = BACKEND_DIR / "models"
    outputs_dir: Path = BACKEND_DIR / "outputs"
    assets_dir: Path = BACKEND_DIR / "assets"

    max_upload_mb: int = 20
    # ~20 minutes of spoken English at a natural pace (~900 chars/minute).
    max_script_chars: int = 20_000
    max_prompt_chars: int = 1_000

    # Talking head runs at roughly 1-3 minutes of processing per minute of script,
    # so a 20-minute script can legitimately take over an hour.
    job_timeout_s: float = 7_200.0
    recent_jobs_limit: int = 20

    wan_variant: str = "ti2v-5b"
    vram_reserve_gb: float = 2.0
    s2_offload: OffloadPolicy = "cpu"
    musetalk_offload: OffloadPolicy = "cpu"
    wan_offload: OffloadPolicy = "cpu"

    log_format: Literal["pretty", "json"] = "pretty"

    @field_validator("models_dir", "outputs_dir", "assets_dir")
    @classmethod
    def _resolve_relative_to_backend(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def voices_dir(self) -> Path:
        return self.assets_dir / "voices"

    def ensure_dirs(self) -> None:
        for directory in (self.models_dir, self.outputs_dir, self.assets_dir, self.voices_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
