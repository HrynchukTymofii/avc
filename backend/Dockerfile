# AI Video Studio backend: CUDA 12.4 runtime, Python 3.11, PyTorch cu121,
# FFmpeg, fish-speech (S2 Pro) and MuseTalk from pinned git checkouts.
#
# Model weights are NOT baked in — they live in a volume mounted at /app/models
# and are downloaded on the host by scripts/download_models.sh.
#
# Version matrix (do not bump pieces independently):
#   torch 2.4.1+cu121  — newest torch with prebuilt mmcv wheels; this runtime
#                        image has no nvcc, so mmcv must never build from source
#   mmcv 2.2.0         — prebuilt wheel from download.openmmlab.com/mmcv/dist/cu121/torch2.4
#   mmpose 1.3.2       — accepts mmcv <=3.0.0; its model registry imports mmdet
#   mmdet 3.3.0        — import-time mmcv ceiling widened by one sed below
#   fish-speech v2.0.0-beta — upstream pins torch==2.8.0 out of convenience; its
#                        inference code uses no 2.8-only APIs, so the pin is
#                        relaxed at build time instead of replacing our torch

FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# Pin these to the exact refs validated on your instance.
ARG FISH_SPEECH_REF=v2.0.0-beta
ARG MUSETALK_REF=main

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/opt/pip-constraints.txt

# setuptools 81 removed pkg_resources, which older setup.py-based packages
# (mmcv, chumpy, ...) still import. The constraint file also reaches pip's
# isolated build environments, where a plain `pip install setuptools<81`
# would not.
RUN printf 'setuptools<81\n' > /opt/pip-constraints.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common curl git ffmpeg \
        libgl1 libglib2.0-0 libsndfile1 build-essential portaudio19-dev \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --upgrade pip "setuptools<81" wheel

# PyTorch first so later installs see it as satisfied (cu121 wheels bundle
# their own CUDA libraries and run fine on the 12.4 base image).
RUN python3.11 -m pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
        --index-url https://download.pytorch.org/whl/cu121

# MuseTalk: repo on PYTHONPATH + mmpose (DWPose landmarks) via openmim, which
# resolves the prebuilt mmcv wheel matching the installed torch/CUDA.
RUN git clone --depth 1 --branch ${MUSETALK_REF} \
        https://github.com/TMElyralab/MuseTalk.git /opt/MuseTalk \
    && python3.11 -m pip install -r /opt/MuseTalk/requirements.txt \
    && python3.11 -m pip install -U openmim \
    # chumpy (mmpose dep, never imported at runtime here) has a 2018-era
    # setup.py that imports pip and breaks under build isolation — install it
    # against the real environment first so mmpose sees it satisfied.
    && python3.11 -m pip install --no-build-isolation "chumpy==0.70" \
    && python3.11 -m mim install mmengine "mmcv==2.2.0" "mmdet==3.3.0" "mmpose==1.3.2" \
    # mmpose's model registry imports mmdet at import time, and mmdet 3.3.0
    # predates mmcv 2.2.0 so its import-time version assert rejects it —
    # stale ceiling, the combination works; widen it.
    && sed -i "s/mmcv_maximum_version = '2.2.0'/mmcv_maximum_version = '2.3.0'/" \
        /usr/local/lib/python3.11/dist-packages/mmdet/__init__.py \
    && grep -q "mmcv_maximum_version = '2.3.0'" /usr/local/lib/python3.11/dist-packages/mmdet/__init__.py

# fish-speech (S2 Pro inference): relax the torch pin to the version installed
# above (see version matrix), then install from the patched checkout.
RUN git clone --depth 1 --branch ${FISH_SPEECH_REF} \
        https://github.com/fishaudio/fish-speech.git /opt/fish-speech \
    && sed -i -e 's/torch==2\.8\.[0-9]*/torch==2.4.1/g' \
              -e 's/torchaudio==2\.8\.[0-9]*/torchaudio==2.4.1/g' \
        /opt/fish-speech/pyproject.toml \
    && python3.11 -m pip install /opt/fish-speech \
    # fish-speech modules call pyrootutils.setup_root(indicator='.project-root')
    # at import time, walking up from the installed package and expecting its
    # repo checkout; give site-packages the marker so imports work installed.
    && touch /usr/local/lib/python3.11/dist-packages/.project-root

# Pre-cache the S3FD face-detector weights MuseTalk's bundled face_detection
# fetches on first use — adrianbulat.com is slow/flaky, so don't let the first
# job depend on it.
RUN python3.11 -c "from torch.utils.model_zoo import load_url; \
load_url('https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth')"

WORKDIR /app
COPY requirements.txt requirements-gpu.txt ./
# Installed last so the versions this app is written against win any conflicts
# with MuseTalk's older pins (see README troubleshooting).
RUN python3.11 -m pip install -r requirements-gpu.txt

# fish-speech drags in a FlashAttention-3 build that (a) targets Hopper GPUs,
# not the L40S, and (b) crashes diffusers' import-time custom-op registration
# on torch 2.4. Nothing in this stack uses it — remove whatever provides it.
RUN python3.11 -c "import importlib.metadata as md, subprocess, sys; \
mods = md.packages_distributions(); \
dists = sorted({d for m in ('flash_attn_interface', 'flash_attn', 'flash_attn_3') for d in mods.get(m, [])}); \
subprocess.check_call([sys.executable, '-m', 'pip', 'uninstall', '-y'] + dists) if dists else print('no flash-attn packages found')"

# ---- Style LoRA trainer (ostris/ai-toolkit) ---------------------------------------
# Trains Wan2.2 5B character/style LoRAs from the checkpoint already mounted at
# /app/models/wan2.2-ti2v-5b (arch wan22_5b). It needs a newer torch than the
# inference stack's pinned 2.4.1 (mmcv wheel matrix above), so it lives in its
# own venv and the backend invokes it as a subprocess
# (app/services/lora_training.py). cu126 wheels bundle their CUDA runtime and
# run fine on this 12.4 base image.
ARG AI_TOOLKIT_REF=main
RUN git clone --depth 1 --branch ${AI_TOOLKIT_REF} \
        https://github.com/ostris/ai-toolkit.git /opt/ai-toolkit \
    && python3.11 -m venv /opt/trainer-venv \
    && /opt/trainer-venv/bin/pip install --no-cache-dir --upgrade pip "setuptools<81" wheel \
    && /opt/trainer-venv/bin/pip install --no-cache-dir \
        torch==2.7.1 torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu126 \
    && /opt/trainer-venv/bin/pip install --no-cache-dir -r /opt/ai-toolkit/requirements.txt \
    # Build-time canary: the trainer venv must import its own torch and the
    # toolkit entry point must parse — fail the build, not the first training job.
    && /opt/trainer-venv/bin/python -c "import torch; print('trainer torch', torch.__version__)" \
    && /opt/trainer-venv/bin/python -m py_compile /opt/ai-toolkit/run.py

# MuseTalk resolves paths relative to the working directory and imports its
# bundled face_detection package as a top-level module:
#   ./musetalk/utils/dwpose/*.py           -> config shipped in the repo (symlink)
#   ./models/{sd-vae,dwpose,face-parse-bisent} -> the mounted models volume
RUN ln -s /opt/MuseTalk/musetalk /app/musetalk
ENV PYTHONPATH=/opt/MuseTalk:/opt/MuseTalk/musetalk/utils

# Build-time canary for the version matrix: mmcv's compiled ops must load
# against this torch, the DWPose config must build through mmpose's registry,
# the bundled face_detection must import, and the fish-speech entry points the
# app uses must resolve. Fails the build instead of the first job.
RUN python3.11 -c "import sys; sys.path.insert(0, '/opt/MuseTalk/musetalk/utils'); \
import mmcv.ops; \
from mmpose.apis import init_model; \
init_model('/opt/MuseTalk/musetalk/utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py', None, device='cpu'); \
import face_detection; \
from diffusers import AutoencoderKL; \
from fish_speech.models.dac.inference import load_model; \
from fish_speech.models.text2semantic.inference import init_model as _im, generate_long; \
print('dependency smoke test: ok')"

COPY app ./app
COPY assets ./assets

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["python3.11", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
