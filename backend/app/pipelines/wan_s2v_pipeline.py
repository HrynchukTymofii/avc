"""Premium-tier Wan2.2-S2V-14B (speech-to-video talking avatar) — placeholder.

Photo + audio -> fully speech-driven avatar video (head/body motion). Not yet
integrated: official diffusers support is unconfirmed, the model needs ~80 GB
VRAM, and diffusion-per-frame makes it viable only for short clips on the H100
tier (SERVICE_ARCHITECTURE.md section 2). The catalog lists the engine with
implemented=False so the UI can show it as "coming with the premium tier";
this class exists so the integration has a home and a name ("wan-s2v").

Integration sketch (to be validated on the H100):
  checkpoint: Wan-AI/Wan2.2-S2V-14B — audio encoder (wav2vec2) + 14B DiT +
  Wan2.1 VAE; generates in ~5 s chunks conditioned on the previous chunk's
  motion frames, so long audio is a chunk loop with carried state.
"""

from __future__ import annotations

from pathlib import Path

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline


class WanS2VPipeline(ManagedPipeline):
    def __init__(self, checkpoint_dir: Path, *, offload_policy: OffloadPolicy) -> None:
        super().__init__(
            "wan-s2v",
            vram_estimate_gb=40.0,
            vram_peak_gb=70.0,
            offload_policy=offload_policy,
        )
        self._checkpoint_dir = checkpoint_dir

    def load(self) -> None:
        raise NotImplementedError(
            "Wan2.2-S2V-14B is not integrated yet — it lands with the H100 tier "
            "(SERVICE_ARCHITECTURE.md section 2)"
        )

    def to_gpu(self) -> None:
        raise NotImplementedError

    def to_cpu(self) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        pass
