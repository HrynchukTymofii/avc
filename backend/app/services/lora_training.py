"""Style LoRA training job processor (Wan2.2 5B base, ostris/ai-toolkit).

The trainer runs as a subprocess out of its own venv (its torch is newer than
the inference stack's — see backend/Dockerfile). Before it starts, every
managed pipeline is fully unloaded: training needs the whole card, and parking
Wan's ~24 GB in system RAM next to the trainer's own copies would squeeze the
64 GB host (reloads come back from page cache in under a minute).

Progress map: dataset prep 1-2, GPU handoff 2-3, training 3-93 (parsed from the
trainer's step counter), install 94-100.

The training config is written as JSON into a .yaml file — JSON is valid YAML,
so ai-toolkit's loader reads it and the backend needs no YAML dependency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from app.pipelines.manager import ModelManager
from app.queue.job import Job, LoraTrainingParams
from app.queue.worker import ProgressReporter
from app.services.loras import LoraRegistry

log = logging.getLogger(__name__)

# The ai-toolkit run name; also the basename of the final weights file.
RUN_NAME = "style"

_TRAIN_START = 3
_TRAIN_END = 93

_STEP_RE = re.compile(r"(\d+)/(\d+)")


def write_captions(dataset_dir: Path, trigger: str, description: str | None) -> int:
    """Write a caption .txt next to every image; returns the image count.

    Every caption is the trigger word (plus the optional style description) —
    the standard recipe for a style/character LoRA where the trigger word is
    made to carry the whole concept.
    """
    caption = trigger if not description else f"{trigger}, {description}"
    count = 0
    for image in sorted(dataset_dir.iterdir()):
        if image.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        image.with_suffix(".txt").write_text(caption + "\n", encoding="utf-8")
        count += 1
    return count


def build_training_config(
    *,
    run_name: str,
    training_dir: Path,
    dataset_dir: Path,
    model_path: Path,
    steps: int,
) -> dict[str, Any]:
    """ai-toolkit job config for a Wan2.2 5B (arch wan22_5b) LoRA.

    Derived from ai-toolkit's train_lora_wan22_14b_24gb.yaml example. No
    quantization: the 5B transformer (~10 GB) plus the UMT5 encoder fit the
    L40S in bf16, and text embeddings are cached up front anyway. Sampling is
    disabled (sample_every > steps) — previews cost minutes each and the
    result is judged in the studio afterwards.
    """
    return {
        "job": "extension",
        "config": {
            "name": run_name,
            "process": [
                {
                    "type": "sd_trainer",
                    "training_folder": str(training_dir),
                    "device": "cuda:0",
                    "network": {"type": "lora", "linear": 32, "linear_alpha": 32},
                    "save": {
                        "dtype": "float16",
                        "save_every": 500,
                        "max_step_saves_to_keep": 2,
                    },
                    "datasets": [
                        {
                            "folder_path": str(dataset_dir),
                            "caption_ext": "txt",
                            "caption_dropout_rate": 0.05,
                            "num_frames": 1,
                            "resolution": [512, 768, 1024],
                        }
                    ],
                    "train": {
                        "batch_size": 1,
                        "steps": steps,
                        "gradient_accumulation": 1,
                        "train_unet": True,
                        "train_text_encoder": False,
                        "gradient_checkpointing": True,
                        "noise_scheduler": "flowmatch",
                        "timestep_type": "linear",
                        "optimizer": "adamw8bit",
                        "lr": 1e-4,
                        "optimizer_params": {"weight_decay": 1e-4},
                        "dtype": "bf16",
                        "cache_text_embeddings": True,
                    },
                    "model": {
                        "name_or_path": str(model_path),
                        "arch": "wan22_5b",
                        "quantize": False,
                        "quantize_te": False,
                        "low_vram": False,
                    },
                    "sample": {
                        "sampler": "flowmatch",
                        "sample_every": steps + 1,  # never fires
                        "width": 512,
                        "height": 512,
                        "num_frames": 1,
                        "fps": 16,
                        "prompts": [],
                        "neg": "",
                        "seed": 42,
                        "guidance_scale": 4.0,
                        "sample_steps": 25,
                    },
                }
            ],
        },
        "meta": {"name": "[name]", "version": "1.0"},
    }


def parse_step_progress(line: str, total_steps: int) -> float | None:
    """Extract training progress from a trainer output line.

    Only a step counter whose total matches the configured step count is
    trusted — the trainer prints other N/M counters (latent caching over the
    dataset, downloads) that would otherwise make progress jump around.
    """
    for match in _STEP_RE.finditer(line):
        current, total = int(match.group(1)), int(match.group(2))
        if total == total_steps and current <= total:
            return current / total
    return None


def find_final_weights(run_dir: Path, run_name: str = RUN_NAME) -> Path:
    """The trained LoRA: `<run>.safetensors` written at the end of training,
    or the newest intermediate `<run>_NNNNNNNNN.safetensors` save."""
    final = run_dir / f"{run_name}.safetensors"
    if final.is_file():
        return final
    saves = sorted(run_dir.glob(f"{run_name}_*.safetensors"))
    if saves:
        return saves[-1]
    raise RuntimeError(
        f"training produced no LoRA weights under {run_dir} — see train.log"
    )


class LoraTrainingProcessor:
    def __init__(
        self, manager: ModelManager, registry: LoraRegistry, settings: Settings
    ) -> None:
        self._manager = manager
        self._registry = registry
        self._settings = settings

    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        params = job.params
        assert isinstance(params, LoraTrainingParams)

        job_dir = self._settings.outputs_dir / job.id
        training_dir = job_dir / "train"
        config_path = job_dir / "train_config.yaml"

        report(1, "preparing dataset")
        image_count = write_captions(params.dataset_dir, params.trigger, params.description)
        if image_count == 0:
            raise RuntimeError("the training dataset contains no images")
        config = build_training_config(
            run_name=RUN_NAME,
            training_dir=training_dir,
            dataset_dir=params.dataset_dir,
            model_path=self._settings.models_dir / f"wan2.2-{self._settings.wan_variant}",
            steps=params.steps,
        )
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        report(2, "freeing gpu")
        await self._manager.release_gpu()

        report(_TRAIN_START, "training")

        def on_step(fraction: float) -> None:
            progress = _TRAIN_START + fraction * (_TRAIN_END - _TRAIN_START)
            report(int(progress), "training")

        await self._run_trainer(config_path, job_dir / "train.log", on_step, params.steps)

        report(94, "saving style")
        weights = find_final_weights(training_dir / RUN_NAME)
        info = await asyncio.to_thread(
            self._registry.install,
            weights,
            name=params.name,
            trigger=params.trigger,
            steps=params.steps,
            image_count=params.image_count,
        )
        log.info(
            "style training complete",
            extra={"job_id": job.id, "lora_id": info.id, "steps": params.steps},
        )
        return {"lora": info.id}

    async def _run_trainer(
        self,
        config_path: Path,
        log_path: Path,
        on_step: Callable[[float], None],
        total_steps: int,
    ) -> None:
        cmd = [
            str(self._settings.trainer_python),
            str(self._settings.trainer_script),
            str(config_path),
        ]
        log.info("starting trainer", extra={"cmd": " ".join(cmd)})
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(self._settings.trainer_script.parent),
        )
        assert process.stdout is not None
        tail: deque[str] = deque(maxlen=20)
        try:
            with log_path.open("w", encoding="utf-8") as log_file:
                pending = ""
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    pending += chunk.decode("utf-8", errors="replace")
                    # tqdm redraws with \r; treat both separators as line ends.
                    *lines, pending = re.split(r"[\r\n]", pending)
                    for line in lines:
                        if not line.strip():
                            continue
                        log_file.write(line + "\n")
                        tail.append(line.strip())
                        fraction = parse_step_progress(line, total_steps)
                        if fraction is not None:
                            on_step(fraction)
                if pending.strip():
                    log_file.write(pending + "\n")
                    tail.append(pending.strip())
            code = await process.wait()
        except asyncio.CancelledError:
            # Job timeout or server shutdown — take the trainer down with us.
            process.kill()
            raise
        if code != 0:
            detail = " | ".join(list(tail)[-3:]) or "no output"
            raise RuntimeError(f"style training failed (exit {code}): {detail}")
