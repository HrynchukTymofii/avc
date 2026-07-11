"""Premium-tier Wan2.2 T2V-A14B (MoE, two 14B experts) — H100 scaffold.

UNTESTED on real hardware: needs ~80 GB VRAM, so it is registered only when
PREMIUM_ENABLED=true (never on the L40S). The diffusers WanPipeline handles the
two-expert checkpoint transparently, so this subclass only changes the
checkpoint, name, and VRAM budget. Expect live-GPU debugging on first H100
contact before flipping the catalog entry to implemented=True — every model in
this repo has needed it (see SERVICE_ARCHITECTURE.md section 2).
"""

from __future__ import annotations

from pathlib import Path

from app.config import OffloadPolicy
from app.pipelines.wan_pipeline import WanPipeline


class WanA14BPipeline(WanPipeline):
    def __init__(self, checkpoint_dir: Path, *, offload_policy: OffloadPolicy) -> None:
        super().__init__(
            checkpoint_dir,
            offload_policy=offload_policy,
            vram_estimate_gb=60.0,
            vram_peak_gb=75.0,
            name="wan-a14b",
        )
