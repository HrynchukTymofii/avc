"""Premium-tier Wan2.2-Animate-14B (character animation/replacement) — placeholder.

Character image + driving video -> the character performs the video's motion
(reenactment) or replaces the person in it. Same status as S2V: ~80 GB VRAM,
H100-tier work, listed in the catalog with implemented=False until integrated
and debugged on real hardware (SERVICE_ARCHITECTURE.md section 2).

Integration sketch (to be validated on the H100):
  checkpoint: Wan-AI/Wan2.2-Animate-14B-Diffusers exists, which suggests a
  supported diffusers pipeline; inputs are a reference image + pose/driving
  video, so the job API will need a second upload field (driving_video).
"""

from __future__ import annotations

from pathlib import Path

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline


class WanAnimatePipeline(ManagedPipeline):
    def __init__(self, checkpoint_dir: Path, *, offload_policy: OffloadPolicy) -> None:
        super().__init__(
            "wan-animate",
            vram_estimate_gb=40.0,
            vram_peak_gb=70.0,
            offload_policy=offload_policy,
        )
        self._checkpoint_dir = checkpoint_dir

    def load(self) -> None:
        raise NotImplementedError(
            "Wan2.2-Animate-14B is not integrated yet — it lands with the H100 tier "
            "(SERVICE_ARCHITECTURE.md section 2)"
        )

    def to_gpu(self) -> None:
        raise NotImplementedError

    def to_cpu(self) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        pass
