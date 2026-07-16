#!/usr/bin/env bash
# Download all model checkpoints into backend/models/ (or $MODELS_DIR).
#
# Requirements: python3 + `pip install "huggingface_hub[cli]"`, ~60 GB free disk.
# The S2 Pro repo is license-gated: create a free Hugging Face account, accept
# the license at https://huggingface.co/fishaudio/s2-pro, then either run
# `hf auth login` or export HF_TOKEN before running this script.
#
# Downloads resume automatically if interrupted — safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${MODELS_DIR:-$SCRIPT_DIR/../models}"
mkdir -p "$MODELS_DIR"

if ! command -v hf >/dev/null 2>&1; then
    echo "error: the 'hf' CLI is missing. Install it with: pip install 'huggingface_hub[cli]'" >&2
    exit 1
fi

free_gb=$(df -BG --output=avail "$MODELS_DIR" | tail -1 | tr -dc '0-9')
if [ "$free_gb" -lt 50 ]; then
    echo "error: only ${free_gb} GB free at $MODELS_DIR — need at least 50 GB" >&2
    echo "(already-downloaded models are skipped, but leave headroom)" >&2
    exit 1
fi

download() {
    local repo="$1" dest="$2"
    shift 2
    echo "==> $repo -> $dest"
    hf download "$repo" --local-dir "$dest" "$@"
}

echo "Downloading models to $MODELS_DIR (~55 GB total, resumable)"

# --- Fish Audio S2 Pro (~10 GB, license-gated) ------------------------------------
download fishaudio/s2-pro "$MODELS_DIR/s2-pro" || {
    echo "error: S2 Pro download failed. Most likely the license was not accepted" >&2
    echo "or HF_TOKEN is missing — see the header of this script." >&2
    exit 1
}

# --- MuseTalk 1.5 + its companion models (~6 GB) -----------------------------------
download TMElyralab/MuseTalk "$MODELS_DIR/musetalk"
download openai/whisper-tiny "$MODELS_DIR/musetalk/whisper"
# MuseTalk resolves the next three relative to the backend working directory
# (/app/models/... in the container) — the layout below must match exactly.
download stabilityai/sd-vae-ft-mse "$MODELS_DIR/sd-vae"
download yzd-v/DWPose "$MODELS_DIR/dwpose" --include "dw-ll_ucoco_384.pth"
download ManyOtherFunctions/face-parse-bisent "$MODELS_DIR/face-parse-bisent"

# --- Wan2.2 TI2V-5B, diffusers layout (~35 GB) --------------------------------------
# Also the base for style LoRA training (ai-toolkit reads this same checkpoint);
# trained adapters land in $MODELS_DIR/loras/ — no extra downloads needed.
download Wan-AI/Wan2.2-TI2V-5B-Diffusers "$MODELS_DIR/wan2.2-ti2v-5b"

# --- FLUX.1-schnell, image generation (~34 GB, Apache 2.0) ---------------------------
download black-forest-labs/FLUX.1-schnell "$MODELS_DIR/flux.1-schnell"

# --- Premium tier (H100 only; skipped unless PREMIUM_ENABLED=true) -------------------
# ~110 GB extra. Do NOT download on the L40S instance — these models don't fit
# its GPU and only waste disk. See SERVICE_ARCHITECTURE.md section 2.
if [ "${PREMIUM_ENABLED:-false}" = "true" ]; then
    download Wan-AI/Wan2.2-T2V-A14B-Diffusers "$MODELS_DIR/wan2.2-t2v-a14b"
    # Wan2.2-S2V-14B and Wan2.2-Animate-14B land here once integrated.
fi

echo
echo "All models downloaded:"
du -sh "$MODELS_DIR"/* 2>/dev/null || true
echo "Done. Start the app with: docker compose up -d"
