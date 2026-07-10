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
if [ "$free_gb" -lt 70 ]; then
    echo "error: only ${free_gb} GB free at $MODELS_DIR — need at least 70 GB" >&2
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

# --- MuseTalk 1.5 + its companion models (~5 GB) -----------------------------------
download TMElyralab/MuseTalk "$MODELS_DIR/musetalk"
download openai/whisper-tiny "$MODELS_DIR/musetalk/whisper"
download stabilityai/sd-vae-ft-mse "$MODELS_DIR/musetalk/sd-vae"

# --- Wan2.2 TI2V-5B, diffusers layout (~35 GB) --------------------------------------
download Wan-AI/Wan2.2-TI2V-5B-Diffusers "$MODELS_DIR/wan2.2-ti2v-5b"

echo
echo "All models downloaded:"
du -sh "$MODELS_DIR"/* 2>/dev/null || true
echo "Done. Start the app with: docker compose up -d"
