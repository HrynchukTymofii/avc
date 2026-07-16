"""Style LoRA training: dataset prep, trainer config, progress parsing, and the
processor end-to-end against a fake trainer subprocess (no GPU)."""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from app.config import Settings
from app.pipelines.base import ManagedPipeline, PipelineState
from app.pipelines.manager import ModelManager
from app.queue.job import Job, LoraTrainingParams, new_job_id
from app.schemas import JobKind
from app.services.lora_training import (
    RUN_NAME,
    LoraTrainingProcessor,
    build_training_config,
    find_final_weights,
    parse_step_progress,
    write_captions,
)
from app.services.loras import LoraRegistry
from tests.test_processors import ProgressLog


# ---- dataset prep -------------------------------------------------------------------


def test_write_captions(tmp_path: Path) -> None:
    for name in ("a.png", "b.jpg", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    count = write_captions(tmp_path, "zork_style", None)
    assert count == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "zork_style"

    write_captions(tmp_path, "zork_style", "flat pastel cartoon")
    assert (
        tmp_path / "b.txt"
    ).read_text(encoding="utf-8").strip() == "zork_style, flat pastel cartoon"


def test_build_training_config(tmp_path: Path) -> None:
    config = build_training_config(
        run_name=RUN_NAME,
        training_dir=tmp_path / "train",
        dataset_dir=tmp_path / "dataset",
        model_path=tmp_path / "wan2.2-ti2v-5b",
        steps=1500,
    )
    process = config["config"]["process"][0]
    assert process["model"]["arch"] == "wan22_5b"
    assert process["model"]["name_or_path"] == str(tmp_path / "wan2.2-ti2v-5b")
    assert process["train"]["steps"] == 1500
    assert process["datasets"][0]["num_frames"] == 1
    # sampling must never fire mid-run — previews cost minutes each
    assert process["sample"]["sample_every"] > 1500
    # the config is written as JSON into a .yaml file; it must stay serializable
    json.dumps(config)


# ---- progress parsing ----------------------------------------------------------------


def test_parse_step_progress_matches_only_the_step_counter() -> None:
    assert parse_step_progress("style: 500/2000 [10:00<30:00, 1.2it/s]", 2000) == 0.25
    # latent caching over 40 images must not register as training progress
    assert parse_step_progress("caching latents: 40/40", 2000) is None
    assert parse_step_progress("no counters here", 2000) is None
    assert parse_step_progress("", 2000) is None


def test_find_final_weights(tmp_path: Path) -> None:
    run_dir = tmp_path / RUN_NAME
    run_dir.mkdir()
    with pytest.raises(RuntimeError, match="no LoRA weights"):
        find_final_weights(run_dir)

    (run_dir / f"{RUN_NAME}_000000500.safetensors").write_bytes(b"A")
    (run_dir / f"{RUN_NAME}_000001000.safetensors").write_bytes(b"B")
    assert find_final_weights(run_dir).name == f"{RUN_NAME}_000001000.safetensors"

    (run_dir / f"{RUN_NAME}.safetensors").write_bytes(b"FINAL")
    assert find_final_weights(run_dir).name == f"{RUN_NAME}.safetensors"


# ---- processor end-to-end (fake trainer subprocess) -----------------------------------


FAKE_TRAINER = textwrap.dedent(
    """
    import json, pathlib, sys

    config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    process = config["config"]["process"][0]
    steps = process["train"]["steps"]
    run = config["config"]["name"]
    print("caching latents: 10/10")
    for step in (1, steps // 2, steps):
        print(f"{run}: {step}/{steps} [00:01<00:01, 1.0it/s]")
    out_dir = pathlib.Path(process["training_folder"]) / run
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run}.safetensors").write_bytes(b"TRAINED")
    """
)

FAILING_TRAINER = textwrap.dedent(
    """
    import sys
    print("loading model")
    print("CUDA out of memory while loading transformer", file=sys.stderr)
    sys.exit(1)
    """
)


class FakeWan(ManagedPipeline):
    def __init__(self) -> None:
        super().__init__("wan", vram_estimate_gb=18, vram_peak_gb=26, offload_policy="cpu")

    def load(self) -> None: ...
    def to_gpu(self) -> None: ...
    def to_cpu(self) -> None: ...
    def unload(self) -> None: ...


@pytest.fixture
def training_setup(tmp_path: Path):
    trainer_script = tmp_path / "ai-toolkit" / "run.py"
    trainer_script.parent.mkdir(parents=True)
    trainer_script.write_text(FAKE_TRAINER, encoding="utf-8")
    settings = Settings(
        models_dir=tmp_path / "models",
        outputs_dir=tmp_path / "outputs",
        assets_dir=tmp_path / "assets",
        trainer_python=Path(sys.executable),
        trainer_script=trainer_script,
    )
    settings.ensure_dirs()

    job_id = new_job_id()
    dataset_dir = settings.outputs_dir / job_id / "inputs" / "dataset"
    dataset_dir.mkdir(parents=True)
    for index in range(3):
        (dataset_dir / f"img_{index:03d}.png").write_bytes(b"PNG")

    job = Job(
        id=job_id,
        kind=JobKind.LORA_TRAINING,
        params=LoraTrainingParams(
            name="Ink Sketch",
            trigger="1nk_style",
            dataset_dir=dataset_dir,
            image_count=3,
            description="flat pastel cartoon",
            steps=2000,
        ),
        label="Ink Sketch · 3 images",
    )
    return settings, job, trainer_script


async def test_training_processor_end_to_end(training_setup) -> None:
    settings, job, _ = training_setup
    wan = FakeWan()
    manager = ModelManager(
        [wan], vram_reserve_gb=2.0, vram_probe=lambda: 48.0, clear_cuda_cache=lambda: None
    )
    # make wan resident so the processor has something to release
    async with manager.acquire("wan"):
        pass
    assert wan.state is PipelineState.ON_GPU

    registry = LoraRegistry(settings.loras_dir)
    processor = LoraTrainingProcessor(manager, registry, settings)
    progress = ProgressLog()

    outputs = await processor.process(job, progress)

    # the GPU was fully released before training started
    assert wan.state is PipelineState.UNLOADED

    # the style landed in the registry with the job's metadata
    styles = registry.list()
    assert [s.id for s in styles] == [outputs["lora"]]
    assert styles[0].trigger == "1nk_style"
    assert styles[0].weights_path.read_bytes() == b"TRAINED"

    # captions were written next to every image
    params = job.params
    caption = (params.dataset_dir / "img_000.txt").read_text(encoding="utf-8").strip()
    assert caption == "1nk_style, flat pastel cartoon"

    # progress passed through the training stage and only the real step counter
    # moved it (the caching 10/10 line would have jumped straight to 93)
    stages = progress.stages()
    assert "training" in stages and "saving style" in stages
    training_values = [p for p, stage in progress.events if stage == "training"]
    assert max(training_values) == 93
    assert min(training_values) == 3

    # the training log captured the trainer output
    log_text = (settings.outputs_dir / job.id / "train.log").read_text(encoding="utf-8")
    assert "2000/2000" in log_text


async def test_training_processor_surfaces_failure(training_setup) -> None:
    settings, job, trainer_script = training_setup
    trainer_script.write_text(FAILING_TRAINER, encoding="utf-8")
    manager = ModelManager(
        [], vram_reserve_gb=2.0, vram_probe=lambda: 48.0, clear_cuda_cache=lambda: None
    )
    processor = LoraTrainingProcessor(manager, LoraRegistry(settings.loras_dir), settings)

    with pytest.raises(RuntimeError, match="style training failed"):
        await processor.process(job, ProgressLog())
