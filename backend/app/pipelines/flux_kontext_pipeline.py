"""FLUX.1 Kontext dev as a managed pipeline (reference-image editing).

Kontext is an instruction-based editor: it takes a reference image plus a text
instruction and produces a new image that preserves the subject's identity —
change of pose, expression, viewing angle ("show him from the back"), scene.
This is the character-consistency tool the style LoRAs can't provide.

The checkpoint is license-gated on Hugging Face (non-commercial dev license):
accept it at https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev before
running scripts/download_models.sh with HF_TOKEN set.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline
from app.pipelines.wan_pipeline import IMAGE_SIZES, _patch_native_attention_backend

log = logging.getLogger(__name__)

_INFERENCE_STEPS = 28
_DEFAULT_GUIDANCE = 2.5  # upstream-recommended for Kontext dev


class FluxKontextPipeline(ManagedPipeline):
    def __init__(
        self,
        checkpoint_dir: Path,
        *,
        offload_policy: OffloadPolicy,
        vram_estimate_gb: float = 34.0,
        vram_peak_gb: float = 40.0,
    ) -> None:
        super().__init__(
            "flux-kontext",
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
        from diffusers import FluxKontextPipeline as DiffusersFluxKontextPipeline

        # Same torch-2.4 attention incompatibility as Wan/FLUX (enable_gqa kwarg).
        _patch_native_attention_backend()
        if not self._checkpoint_dir.is_dir():
            raise RuntimeError(
                f"FLUX.1-Kontext-dev checkpoint not found at {self._checkpoint_dir} — "
                "accept the license on Hugging Face and run scripts/download_models.sh"
            )
        log.info(
            "loading FLUX.1-Kontext-dev", extra={"checkpoint": str(self._checkpoint_dir)}
        )
        self._pipe = DiffusersFluxKontextPipeline.from_pretrained(
            str(self._checkpoint_dir), torch_dtype=torch.bfloat16
        )
        # Same dtype-kwarg unreliability as the other pipelines: cast each
        # component directly so nothing silently stays fp32.
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
            raise RuntimeError("FLUX Kontext pipeline is not loaded")
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
        image_path: Path | None = None,
        guidance: float | None = None,
    ) -> Path:
        """Edit the reference image per the prompt and write a PNG. Blocking;
        run in a worker thread. Mirrors the other generate_image interfaces,
        plus the reference image (required) and guidance (how strongly the
        instruction pulls away from the reference; 2.5 is balanced)."""
        import torch
        from PIL import Image, ImageOps

        if self._pipe is None or self._device != "cuda":
            raise RuntimeError("FLUX Kontext pipeline must be ON_GPU before generate_image()")
        if image_path is None:
            raise ValueError("the Kontext engine requires a reference image")

        height, width = IMAGE_SIZES[orientation]
        generator = torch.Generator(device=self._device)
        if seed is not None:
            generator.manual_seed(seed)

        with Image.open(image_path) as reference:
            reference = ImageOps.exif_transpose(reference).convert("RGB")

        def step_callback(pipe: Any, step: int, timestep: Any, callback_kwargs: dict) -> dict:
            on_progress((step + 1) / _INFERENCE_STEPS)
            return callback_kwargs

        log.info(
            "generating image (kontext)",
            extra={"orientation": orientation, "guidance": guidance},
        )
        result = self._pipe(
            image=reference,
            prompt=prompt,
            height=height,
            width=width,
            num_inference_steps=_INFERENCE_STEPS,
            guidance_scale=guidance if guidance is not None else _DEFAULT_GUIDANCE,
            max_sequence_length=512,
            generator=generator,
            callback_on_step_end=step_callback,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.images[0].save(out_path)
        return out_path
