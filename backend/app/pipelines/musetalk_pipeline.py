"""MuseTalk 1.5 as a managed pipeline (lip-sync a single avatar image to audio).

Integrates the MuseTalk repo (cloned at a pinned commit onto PYTHONPATH in the
Docker image) the same way its own realtime inference script drives it:
whisper audio features -> positional encoding -> UNet latent prediction ->
VAE decode -> blend the animated mouth region back into the avatar frame.

The avatar is one still image, so face detection, cropping, and VAE encoding
happen once per job; the per-frame loop is UNet + decode + blend only. Output
is a silent 25 fps video — the talking-head service muxes the speech track in
with FFmpeg afterwards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import OffloadPolicy
from app.pipelines.base import ManagedPipeline

log = logging.getLogger(__name__)

_FPS = 25
_BATCH_SIZE = 8


class MuseTalkPipeline(ManagedPipeline):
    def __init__(
        self,
        checkpoint_dir: Path,
        *,
        offload_policy: OffloadPolicy,
        vram_estimate_gb: float = 6.0,
        vram_peak_gb: float = 9.0,
    ) -> None:
        super().__init__(
            "musetalk",
            vram_estimate_gb=vram_estimate_gb,
            vram_peak_gb=vram_peak_gb,
            offload_policy=offload_policy,
        )
        self._checkpoint_dir = checkpoint_dir
        self._vae: Any = None
        self._unet: Any = None
        self._pe: Any = None
        self._whisper: Any = None
        self._audio_processor: Any = None
        self._device = "cpu"

    # ---- ManagedPipeline ----------------------------------------------------

    def load(self) -> None:
        if self._unet is not None:
            return
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.utils import load_all_model
        from transformers import WhisperModel

        root = self._checkpoint_dir
        if not root.is_dir():
            raise RuntimeError(
                f"MuseTalk checkpoints not found at {root} — run scripts/download_models.sh first"
            )
        log.info("loading MuseTalk", extra={"checkpoint": str(root)})
        self._vae, self._unet, self._pe = load_all_model(
            unet_model_path=str(root / "musetalkV15" / "unet.pth"),
            vae_type="sd-vae",
            unet_config=str(root / "musetalkV15" / "musetalk.json"),
            device="cpu",
        )
        whisper_dir = str(root / "whisper")
        self._whisper = WhisperModel.from_pretrained(whisper_dir).eval()
        self._whisper.requires_grad_(False)
        self._audio_processor = AudioProcessor(feature_extractor_path=whisper_dir)
        self._device = "cpu"

    def to_gpu(self) -> None:
        self._move("cuda")

    def to_cpu(self) -> None:
        self._move("cpu")
        import torch

        torch.cuda.empty_cache()

    def unload(self) -> None:
        self._vae = None
        self._unet = None
        self._pe = None
        self._whisper = None
        self._audio_processor = None
        self._device = "cpu"

    def _move(self, device: str) -> None:
        if self._unet is None:
            raise RuntimeError("MuseTalk pipeline is not loaded")
        self._vae.vae.to(device)
        self._unet.model.to(device)
        self._pe.to(device)
        self._whisper.to(device)
        self._device = device

    # ---- generation ------------------------------------------------------------

    def generate(
        self,
        avatar_path: Path,
        audio_path: Path,
        out_path: Path,
        on_progress: Callable[[float], None],
    ) -> Path:
        """Lip-sync the avatar image to the audio; writes a silent 25 fps video
        to out_path. Blocking; run in a worker thread."""
        import cv2
        import numpy as np
        import torch
        from musetalk.utils.blending import get_image
        from musetalk.utils.preprocessing import get_landmark_and_bbox
        from musetalk.utils.utils import datagen

        if self._unet is None or self._device != "cuda":
            raise RuntimeError("MuseTalk pipeline must be ON_GPU before generate()")

        frame = cv2.imread(str(avatar_path))
        if frame is None:
            raise ValueError("avatar image could not be read")

        # -- one-time avatar preparation ------------------------------------------
        coord_list, frame_list = get_landmark_and_bbox([str(avatar_path)], 0)
        bbox = coord_list[0]
        if bbox is None or -1 in bbox:
            raise ValueError(
                "no face detected in the avatar image — use a clear, front-facing portrait"
            )
        x1, y1, x2, y2 = bbox
        crop = frame_list[0][y1:y2, x1:x2]
        crop = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        input_latent = self._vae.get_latents_for_unet(crop)

        # -- audio features ----------------------------------------------------------
        weight_dtype = self._unet.model.dtype
        whisper_features, librosa_length = self._audio_processor.get_audio_feature(
            str(audio_path)
        )
        whisper_chunks = self._audio_processor.get_whisper_chunk(
            whisper_features,
            self._device,
            weight_dtype,
            self._whisper,
            librosa_length,
            fps=_FPS,
        )
        total_frames = len(whisper_chunks)
        if total_frames == 0:
            raise RuntimeError("audio produced no feature frames")

        # -- frame loop ----------------------------------------------------------------
        height, width = frame.shape[:2]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), _FPS, (width, height)
        )
        try:
            timesteps = torch.tensor([0], device=self._device)
            latent_batches = datagen(
                whisper_chunks, [input_latent] * total_frames, _BATCH_SIZE
            )
            done = 0
            with torch.inference_mode():
                for audio_batch, latent_batch in latent_batches:
                    audio_batch = self._pe(audio_batch.to(self._device))
                    latent_batch = latent_batch.to(device=self._device, dtype=weight_dtype)
                    pred_latents = self._unet.model(
                        latent_batch, timesteps, encoder_hidden_states=audio_batch
                    ).sample
                    recon_frames = self._vae.decode_latents(pred_latents)
                    for res_frame in recon_frames:
                        res_frame = cv2.resize(
                            np.asarray(res_frame, dtype=np.uint8), (x2 - x1, y2 - y1)
                        )
                        composed = get_image(frame, res_frame, [x1, y1, x2, y2])
                        writer.write(composed)
                    done += len(recon_frames)
                    on_progress(min(1.0, done / total_frames))
        finally:
            writer.release()

        log.info("lip-sync rendered", extra={"frames": total_frames, "fps": _FPS})
        return out_path
