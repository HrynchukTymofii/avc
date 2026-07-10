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
#   mmpose 1.3.2       — accepts mmcv <=3.0.0; mmdet is NOT installed (MuseTalk
#                        only uses mmpose/DWPose, and mmdet would reject mmcv 2.2.0)
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
    && python3.11 -m mim install mmengine "mmcv==2.2.0" "mmpose==1.3.2"

# fish-speech (S2 Pro inference): relax the torch pin to the version installed
# above (see version matrix), then install from the patched checkout.
RUN git clone --depth 1 --branch ${FISH_SPEECH_REF} \
        https://github.com/fishaudio/fish-speech.git /opt/fish-speech \
    && sed -i -e 's/torch==2\.8\.[0-9]*/torch==2.4.1/g' \
              -e 's/torchaudio==2\.8\.[0-9]*/torchaudio==2.4.1/g' \
        /opt/fish-speech/pyproject.toml \
    && python3.11 -m pip install /opt/fish-speech

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
from fish_speech.models.dac.inference import load_model; \
from fish_speech.models.text2semantic.inference import init_model as _im, generate_long; \
print('dependency smoke test: ok')"

COPY app ./app
COPY assets ./assets

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["python3.11", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
