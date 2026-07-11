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
# Single-frame generation reuses the video model as a text-to-image model.
# All dimensions must be multiples of 16 (VAE spatial compression).
IMAGE_SIZES: dict[str, tuple[int, int]] = {  # orientation -> (height, width)
    "landscape": (704, 1280),
    "portrait": (1280, 704),
    "square": (960, 960),
}
# Wan's recommended default negative prompt (quality/artifact suppression).
_NEGATIVE_PROMPT = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
    "杂乱的背景，三条腿，背景人很多，倒着走"
)


def _patch_native_attention_backend() -> None:
    """diffusers 0.35's NATIVE attention backend passes enable_gqa to
    F.scaled_dot_product_attention unconditionally in its body; torch < 2.5
    (our pin, for the mmcv wheel matrix) rejects the kwarg with a TypeError.
    Re-register the backend without it — enable_gqa is a perf hint, not a
    behavior change, and Wan's attention is not grouped-query anyway."""
    import torch
    from diffusers.models import attention_dispatch

    def _native_attention_no_gqa(
        query: Any,
        key: Any,
        value: Any,
        attn_mask: Any = None,
        dropout_p: float = 0.0,
        is_causal: bool = False,
        scale: float | None = None,
        enable_gqa: bool = False,
    ) -> Any:
        query, key, value = (x.permute(0, 2, 1, 3) for x in (query, key, value))
        out = torch.nn.functional.scaled_dot_product_attention(
            query=query,
            key=key,
            value=value,
            attn_mask=attn_mask,
            dropout_p=dropout_p,
            is_causal=is_causal,
            scale=scale,
        )
        return out.permute(0, 2, 1, 3)

    registry = attention_dispatch._AttentionBackendRegistry
    registry._backends[attention_dispatch.AttentionBackendName.NATIVE] = _native_attention_no_gqa


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
        name: str = "wan",
    ) -> None:
        super().__init__(
            name,
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

        _patch_native_attention_backend()
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
        # No vae.enable_tiling(): diffusers 0.35's tiled decode is broken for
        # the Wan2.2 VAE (temporal-chunk shape mismatch in avg_shortcut).
        # Second view over the same weights — supports image conditioning.
        # Non-fatal: some checkpoints (e.g. the A14B T2V expert pair) may not
        # map onto the i2v pipeline; text-to-video still works without it.
        try:
            self._i2v = WanImageToVideoPipeline.from_pipe(self._t2v)
        except Exception:
            log.warning("i2v view unavailable for this checkpoint — reference images disabled")
            self._i2v = None
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
        import torch

        # Plain .to(device) upcasts these models to fp32 in this environment
        # (verified with assets/diag_wan_vram.py: 23 GB bf16 became 43 GB fp32
        # and OOM'd the L40S). An explicit dtype in the same call keeps bf16.
        # i2v shares the same modules; one move covers both.
        self._t2v.to(device, torch.bfloat16)
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
        orientation: str | None = None,
    ) -> Path:
        """Generate a clip and write it (H.264 re-encode happens in the service).
        Blocking; run in a worker thread. `orientation` (a key of IMAGE_SIZES)
        overrides the default landscape canvas."""
        import torch
        from diffusers.utils import export_to_video

        if self._t2v is None or self._device != "cuda":
            raise RuntimeError("Wan pipeline must be ON_GPU before generate()")

        height, width = IMAGE_SIZES[orientation] if orientation else (_HEIGHT, _WIDTH)
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
            height=height,
            width=width,
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
            if self._i2v is None:
                raise ValueError("this model does not support reference images")
            result = self._i2v(image=self._prepare_image(image_path, width, height), **common)
        else:
            result = self._t2v(**common)

        frames = result.frames[0]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames, str(out_path), fps=_FPS)
        return out_path

    def generate_image(
        self,
        prompt: str,
        orientation: str,
        out_path: Path,
        on_progress: Callable[[float], None],
        seed: int | None = None,
    ) -> Path:
        """Generate a single frame and write it as a PNG. Blocking; run in a
        worker thread."""
        import numpy as np
        import torch
        from PIL import Image

        if self._t2v is None or self._device != "cuda":
            raise RuntimeError("Wan pipeline must be ON_GPU before generate_image()")

        height, width = IMAGE_SIZES[orientation]
        generator = torch.Generator(device=self._device)
        if seed is not None:
            generator.manual_seed(seed)

        def step_callback(pipe: Any, step: int, timestep: Any, callback_kwargs: dict) -> dict:
            on_progress((step + 1) / _INFERENCE_STEPS)
            return callback_kwargs

        log.info("generating image", extra={"orientation": orientation})
        result = self._t2v(
            prompt=prompt,
            negative_prompt=_NEGATIVE_PROMPT,
            height=height,
            width=width,
            num_frames=1,
            num_inference_steps=_INFERENCE_STEPS,
            guidance_scale=_GUIDANCE_SCALE,
            generator=generator,
            callback_on_step_end=step_callback,
        )

        frame = result.frames[0][0]
        if frame.dtype != np.uint8:
            frame = np.clip(np.rint(frame * 255), 0, 255).astype(np.uint8)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame).save(out_path)
        return out_path

    @staticmethod
    def _prepare_image(image_path: Path, width: int, height: int) -> Any:
        """Fit the reference image to the target canvas (cover + center-crop)
        so conditioning matches the output aspect ratio."""
        from PIL import Image, ImageOps

        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            return ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)
