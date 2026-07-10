"""ManagedPipeline: the contract every GPU pipeline implements.

A pipeline is a state machine whose device placement the ModelManager controls:

    UNLOADED --load()--> ON_CPU --to_gpu()--> ON_GPU
        ^                  |  ^                  |
        +----unload()------+  +----to_cpu()------+

Pipelines implement the *mechanics* of each transition; the manager decides
*when* transitions happen, updates `state`, and logs every move. All four
methods are blocking (they move gigabytes) and are always called via
asyncio.to_thread from the manager.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from app.config import OffloadPolicy


class PipelineState(str, Enum):
    UNLOADED = "unloaded"
    ON_CPU = "on_cpu"
    ON_GPU = "on_gpu"


class ManagedPipeline(ABC):
    def __init__(
        self,
        name: str,
        *,
        vram_estimate_gb: float,
        vram_peak_gb: float,
        offload_policy: OffloadPolicy,
    ) -> None:
        if vram_peak_gb < vram_estimate_gb:
            raise ValueError("vram_peak_gb must be >= vram_estimate_gb")
        self.name = name
        self.vram_estimate_gb = vram_estimate_gb
        self.vram_peak_gb = vram_peak_gb
        self.offload_policy = offload_policy
        self.state = PipelineState.UNLOADED
        self.last_used_at = 0.0  # monotonic timestamp, maintained by the manager

    @abstractmethod
    def load(self) -> None:
        """Read checkpoints from disk into CPU memory. Idempotent."""

    @abstractmethod
    def to_gpu(self) -> None:
        """Move weights to CUDA. Called only when state is ON_CPU."""

    @abstractmethod
    def to_cpu(self) -> None:
        """Move weights to system RAM and release their VRAM."""

    @abstractmethod
    def unload(self) -> None:
        """Drop all weights, freeing both CPU and GPU memory."""
