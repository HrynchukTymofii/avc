"""FLUX.1-schnell as a managed pipeline (text-to-image).

schnell is the Apache-2.0 distilled variant (4 steps, no guidance) — chosen
over FLUX.1-dev for license safety in a future paid service. Shares the
orientation canvas sizes with the Wan pipeline so the image API is uniform.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline
from app.pipelines.wan_pipeline import IMAGE_SIZES

log = logging.getLogger(__name__)

_INFERENCE_STEPS = 4  # schnell is step-distilled; 4 is the intended setting
_GUIDANCE_SCALE = 0.0


class FluxPipeline(ManagedPipeline):
    def __init__(
        self,
        checkpoint_dir: Path,
        *,
        offload_policy: OffloadPolicy,
        vram_estimate_gb: float = 34.0,
        vram_peak_gb: float = 40.0,
    ) -> None:
        super().__init__(
            "flux",
            vram_estimate_gb=vram_estimate_gb,
            vram_peak_gb=vram_peak_gb,
            offload_policy=offload_policy,
        )
        self._checkpoint_dir = checkpoint_dir
        self._pipe: Any = None
        self._device = "cpu"

    # ---- ManagedPipeline ----------------------------------------------------

    def load(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from diffusers import FluxPipeline as DiffusersFluxPipeline

        if not self._checkpoint_dir.is_dir():
            raise RuntimeError(
                f"FLUX.1-schnell checkpoint not found at {self._checkpoint_dir} — "
                "run scripts/download_models.sh first"
            )
        log.info("loading FLUX.1-schnell", extra={"checkpoint": str(self._checkpoint_dir)})
        self._pipe = DiffusersFluxPipeline.from_pretrained(
            str(self._checkpoint_dir), torch_dtype=torch.bfloat16
        )
        # Same dtype-kwarg unreliability as the Wan pipeline (see there): cast
        # each component directly so nothing silently stays fp32.
        for name in ("transformer", "text_encoder", "text_encoder_2", "vae"):
            module = getattr(self._pipe, name, None)
            if module is None:
                continue
            dtype = next(module.parameters()).dtype
            if dtype != torch.bfloat16:
                log.warning("%s loaded as %s — casting to bfloat16", name, dtype)
                module.to(dtype=torch.bfloat16)
        self._device = "cpu"

    def to_gpu(self) -> None:
        self._move("cuda")

    def to_cpu(self) -> None:
        self._move("cpu")
        import torch

        torch.cuda.empty_cache()

    def unload(self) -> None:
        self._pipe = None
        self._device = "cpu"

    def _move(self, device: str) -> None:
        if self._pipe is None:
            raise RuntimeError("FLUX pipeline is not loaded")
        import torch

        # Explicit dtype in the move — device-only .to() upcasts to fp32 in
        # this environment (same failure mode as the Wan pipeline).
        self._pipe.to(device, torch.bfloat16)
        self._device = device

    # ---- generation ------------------------------------------------------------

    def generate_image(
        self,
        prompt: str,
        orientation: str,
        out_path: Path,
        on_progress: Callable[[float], None],
        seed: int | None = None,
    ) -> Path:
        """Generate a single image and write it as a PNG. Blocking; run in a
        worker thread. Mirrors WanPipeline.generate_image's interface."""
        import torch

        if self._pipe is None or self._device != "cuda":
            raise RuntimeError("FLUX pipeline must be ON_GPU before generate_image()")

        height, width = IMAGE_SIZES[orientation]
        generator = torch.Generator(device=self._device)
        if seed is not None:
            generator.manual_seed(seed)

        def step_callback(pipe: Any, step: int, timestep: Any, callback_kwargs: dict) -> dict:
            on_progress((step + 1) / _INFERENCE_STEPS)
            return callback_kwargs

        log.info("generating image (flux)", extra={"orientation": orientation})
        result = self._pipe(
            prompt=prompt,
            height=height,
            width=width,
            num_inference_steps=_INFERENCE_STEPS,
            guidance_scale=_GUIDANCE_SCALE,
            max_sequence_length=256,  # schnell's text-encoder limit
            generator=generator,
            callback_on_step_end=step_callback,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.images[0].save(out_path)
        return out_path
