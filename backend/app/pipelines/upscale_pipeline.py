"""Real-ESRGAN as a managed pipeline (image and per-frame video upscaling).

Two RRDBNet variants live in one pipeline: **photo** (RealESRGAN_x4plus, the
general model) and **anime** (RealESRGAN_x4plus_anime_6B, tuned for drawn/flat
art — the right pick for stylized character content). Both are tiny next to
the diffusion stacks (~64/18 MB weights); RealESRGANer's tiled inference keeps
the VRAM peak in the single digits even for large inputs, and fp16 is enabled
on GPU.

Both models natively upscale 4x; the requested output scale (2 or 4) is
applied by RealESRGANer's `outscale` resampling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline

log = logging.getLogger(__name__)

NATIVE_SCALE = 4
OUTPUT_SCALES = (2, 4)
_TILE = 512

# variant -> (weights filename, RRDBNet num_block)
VARIANTS: dict[str, tuple[str, int]] = {
    "photo": ("RealESRGAN_x4plus.pth", 23),
    "anime": ("RealESRGAN_x4plus_anime_6B.pth", 6),
}


class UpscalePipeline(ManagedPipeline):
    def __init__(
        self,
        weights_dir: Path,
        *,
        offload_policy: OffloadPolicy,
        vram_estimate_gb: float = 1.0,
        vram_peak_gb: float = 6.0,
        name: str = "upscale",
    ) -> None:
        super().__init__(
            name,
            vram_estimate_gb=vram_estimate_gb,
            vram_peak_gb=vram_peak_gb,
            offload_policy=offload_policy,
        )
        self._weights_dir = weights_dir
        self._upsamplers: dict[str, Any] = {}
        self._device = "cpu"

    # ---- ManagedPipeline ----------------------------------------------------

    def load(self) -> None:
        if self._upsamplers:
            return
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

        for variant, (filename, num_block) in VARIANTS.items():
            weights = self._weights_dir / filename
            if not weights.is_file():
                raise RuntimeError(
                    f"Real-ESRGAN weights not found at {weights} — "
                    "run scripts/download_models.sh first"
                )
            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=num_block,
                num_grow_ch=32,
                scale=NATIVE_SCALE,
            )
            # RealESRGANer loads the state dict into `model` and owns tiling.
            self._upsamplers[variant] = RealESRGANer(
                scale=NATIVE_SCALE,
                model_path=str(weights),
                model=model,
                tile=_TILE,
                tile_pad=10,
                pre_pad=0,
                half=False,
                device=torch.device("cpu"),
            )
            log.info("loaded Real-ESRGAN variant", extra={"variant": variant})
        self._device = "cpu"

    def to_gpu(self) -> None:
        import torch

        for upsampler in self._upsamplers.values():
            upsampler.model = upsampler.model.half().to("cuda")
            upsampler.device = torch.device("cuda")
            upsampler.half = True  # enhance() casts inputs to match
        self._device = "cuda"

    def to_cpu(self) -> None:
        import torch

        for upsampler in self._upsamplers.values():
            upsampler.model = upsampler.model.float().to("cpu")
            upsampler.device = torch.device("cpu")
            upsampler.half = False
        self._device = "cpu"
        torch.cuda.empty_cache()

    def unload(self) -> None:
        self._upsamplers = {}
        self._device = "cpu"

    # ---- upscaling ------------------------------------------------------------

    def upscale_image(self, src: Path, dst: Path, *, variant: str, scale: int) -> Path:
        """Upscale one image file to `dst` (always PNG; alpha is preserved).
        Blocking; run in a worker thread."""
        import cv2

        if not self._upsamplers or self._device != "cuda":
            raise RuntimeError("upscale pipeline must be ON_GPU before upscale_image()")
        if variant not in VARIANTS:
            raise ValueError(f"unknown upscale variant {variant!r}")
        if scale not in OUTPUT_SCALES:
            raise ValueError(f"scale must be one of {OUTPUT_SCALES}")

        image = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError(f"could not decode image {src.name}")
        output, _ = self._upsamplers[variant].enhance(image, outscale=scale)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(dst), output):
            raise RuntimeError(f"could not write upscaled image {dst.name}")
        return dst
