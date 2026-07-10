# AI Video Studio backend: CUDA 12.4 runtime, Python 3.11, PyTorch cu124,
# FFmpeg, fish-speech (S2 Pro) and MuseTalk from pinned git checkouts.
#
# Model weights are NOT baked in — they live in a volume mounted at /app/models
# and are downloaded on the host by scripts/download_models.sh.

FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# Pin these to the exact refs validated on your instance. `main` tracks upstream
# and is fine for a first deploy; freeze the working commit hashes afterwards.
ARG FISH_SPEECH_REF=main
ARG MUSETALK_REF=main

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common curl git ffmpeg \
        libgl1 libglib2.0-0 libsndfile1 build-essential \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --upgrade pip setuptools wheel

# PyTorch first (CUDA 12.4 wheels) so later installs see it as satisfied.
RUN python3.11 -m pip install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu124

# MuseTalk: repo on PYTHONPATH + its mm* stack via openmim.
RUN git clone --depth 1 --branch ${MUSETALK_REF} \
        https://github.com/TMElyralab/MuseTalk.git /opt/MuseTalk \
    && python3.11 -m pip install -r /opt/MuseTalk/requirements.txt \
    && python3.11 -m pip install -U openmim \
    && python3.11 -m mim install mmengine "mmcv>=2.0.1" "mmdet>=3.1.0" "mmpose>=1.1.0"

# fish-speech (S2 Pro inference).
RUN python3.11 -m pip install \
        "fish-speech @ git+https://github.com/fishaudio/fish-speech.git@${FISH_SPEECH_REF}"

WORKDIR /app
COPY requirements.txt requirements-gpu.txt ./
# Installed last so the versions this app is written against win any conflicts
# with MuseTalk's older pins (see README troubleshooting).
RUN python3.11 -m pip install -r requirements-gpu.txt

COPY app ./app
COPY assets ./assets

ENV PYTHONPATH=/opt/MuseTalk

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["python3.11", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
