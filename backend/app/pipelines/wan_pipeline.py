"""Wan2.2 TI2V-5B as a managed pipeline (text-to-video and image-to-video).

One diffusers checkpoint provides both modes: the T2V pipeline is loaded from
disk, and the I2V pipeline is created as a second view over the *same*
components (shared transformer/VAE/text encoder — no extra memory). Native
output is 704x1280 at 24 fps; frame counts must be 4k+1 for the causal VAE,
so 3/4/5 seconds map to 73/97/121 frames.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline

log = logging.getLogger(__name__)

_FPS = 24
_HEIGHT = 704
_WIDTH = 1280
_INFERENCE_STEPS = 40
_GUIDANCE_SCALE = 5.0
# Wan's recommended default negative prompt (quality/artifact suppression).
_NEGATIVE_PROMPT = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
    "杂乱的背景，三条腿，背景人很多，倒着走"
)


def frames_for_duration(duration_s: int) -> int:
    """Valid frame count (4k+1, required by the causal VAE) for the requested
    duration at 24 fps: 3/4/5 s -> 73/97/121."""
    frames = duration_s * _FPS + 1
    return frames - (frames - 1) % 4


class WanPipeline(ManagedPipeline):
    def __init__(
        self,
        checkpoint_dir: Path,
        *,
        offload_policy: OffloadPolicy,
        vram_estimate_gb: float = 18.0,
        vram_peak_gb: float = 27.0,
    ) -> None:
        super().__init__(
            "wan",
            vram_estimate_gb=vram_estimate_gb,
            vram_peak_gb=vram_peak_gb,
            offload_policy=offload_policy,
        )
        self._checkpoint_dir = checkpoint_dir
        self._t2v: Any = None
        self._i2v: Any = None
        self._device = "cpu"

    # ---- ManagedPipeline ----------------------------------------------------

    def load(self) -> None:
        if self._t2v is not None:
            return
        import torch
        from diffusers import WanImageToVideoPipeline
        from diffusers import WanPipeline as DiffusersWanPipeline

        if not self._checkpoint_dir.is_dir():
            raise RuntimeError(
                f"Wan2.2 checkpoint not found at {self._checkpoint_dir} — "
                "run scripts/download_models.sh first"
            )
        log.info("loading Wan2.2 TI2V-5B", extra={"checkpoint": str(self._checkpoint_dir)})
        # dtype kwargs are unreliable across this diffusers/transformers combo:
        # the fp32 text encoder (~23 GB on disk) kept coming out fp32 even after
        # a pipeline-level .to(dtype), OOMing the 44 GB L40S. Cast each module
        # directly — nn.Module.to() can't be silently skipped.
        self._t2v = DiffusersWanPipeline.from_pretrained(
            str(self._checkpoint_dir), torch_dtype=torch.bfloat16
        )
        for name in ("transformer", "text_encoder", "vae"):
            module = getattr(self._t2v, name)
            dtype = next(module.parameters()).dtype
            if dtype != torch.bfloat16:
                log.warning("%s loaded as %s — casting to bfloat16", name, dtype)
                module.to(dtype=torch.bfloat16)
        log.info(
            "wan component dtypes",
            extra={
                name: str(next(getattr(self._t2v, name).parameters()).dtype)
                for name in ("transformer", "text_encoder", "vae")
            },
        )
        # Tiled VAE decode: full 73-frame 704x1280 decode can spike VRAM at the
        # very end of a run; tiling trades a little speed for safety.
        self._t2v.vae.enable_tiling()
        # Second view over the same weights — supports image conditioning.
        self._i2v = WanImageToVideoPipeline.from_pipe(self._t2v)
        self._device = "cpu"

    def to_gpu(self) -> None:
        self._move("cuda")

    def to_cpu(self) -> None:
        self._move("cpu")
        import torch

        torch.cuda.empty_cache()

    def unload(self) -> None:
        self._t2v = None
        self._i2v = None
        self._device = "cpu"

    def _move(self, device: str) -> None:
        if self._t2v is None:
            raise RuntimeError("Wan pipeline is not loaded")
        self._t2v.to(device)  # i2v shares the same modules; one move covers both
        self._device = device

    # ---- generation ------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        duration_s: int,
        image_path: Path | None,
        out_path: Path,
        on_progress: Callable[[float], None],
        seed: int | None = None,
    ) -> Path:
        """Generate a clip and write it (H.264 re-encode happens in the service).
        Blocking; run in a worker thread."""
        import torch
        from diffusers.utils import export_to_video

        if self._t2v is None or self._device != "cuda":
            raise RuntimeError("Wan pipeline must be ON_GPU before generate()")

        num_frames = frames_for_duration(duration_s)
        generator = torch.Generator(device=self._device)
        if seed is not None:
            generator.manual_seed(seed)

        def step_callback(pipe: Any, step: int, timestep: Any, callback_kwargs: dict) -> dict:
            on_progress((step + 1) / _INFERENCE_STEPS)
            return callback_kwargs

        common: dict[str, Any] = dict(
            prompt=prompt,
            negative_prompt=_NEGATIVE_PROMPT,
            height=_HEIGHT,
            width=_WIDTH,
            num_frames=num_frames,
            num_inference_steps=_INFERENCE_STEPS,
            guidance_scale=_GUIDANCE_SCALE,
            generator=generator,
            callback_on_step_end=step_callback,
        )

        log.info(
            "generating b-roll",
            extra={"mode": "i2v" if image_path else "t2v", "frames": num_frames},
        )
        if image_path is not None:
            result = self._i2v(image=self._prepare_image(image_path), **common)
        else:
            result = self._t2v(**common)

        frames = result.frames[0]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames, str(out_path), fps=_FPS)
        return out_path

    @staticmethod
    def _prepare_image(image_path: Path) -> Any:
        """Fit the reference image to the native 1280x704 canvas (cover + center-crop)
        so conditioning matches the output aspect ratio."""
        from PIL import Image, ImageOps

        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            return ImageOps.fit(image, (_WIDTH, _HEIGHT), Image.Resampling.LANCZOS)
