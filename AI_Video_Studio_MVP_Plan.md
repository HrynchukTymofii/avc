# AI Video Studio — Final MVP Plan

You are a senior full-stack engineer. Build a complete, production-ready MVP web application with **two generation tools** sharing one backend and one GPU. The project must be fully functional — no placeholder implementations, no mock functions, no TODOs.

---

## Product Overview

A single web app with two pages:

**Page 1 — Talking Head Studio**
User uploads an avatar image (PNG/JPG), selects a voice, and pastes a script. The system generates a voiceover with **Fish Audio S2 Pro** (self-hosted, voice-cloned from bundled reference clips) and animates the avatar with **MuseTalk**, producing a lip-synced talking-head video.

**Page 2 — B-Roll Generator**
User enters a text prompt and optionally uploads a reference image. The system generates a short (3–5 second) video clip using **Wan2.2** (text-to-video and image-to-video). Output clips are downloaded and cut into Premiere Pro manually — no in-app editing needed.

Both pages submit jobs to the same backend queue and poll for status.

---

## Tech Stack

**Frontend**
- Next.js 15, App Router
- TypeScript
- Tailwind CSS
- shadcn/ui

**Backend**
- Python 3.11
- FastAPI
- PyTorch (CUDA)
- FFmpeg

**AI Models (official pretrained checkpoints only)**
- Fish Audio S2 Pro — text-to-speech / voice cloning, multi-language (80+ languages). Open weights from `huggingface.co/fishaudio/s2-pro` (~10GB VRAM in bf16), run in-process via the `fish-speech` inference code. Voices are preset 10–30s reference clips bundled in `backend/assets/voices/` — no transcript needed. (Fish Audio Research License: free for non-commercial/hobby use.)
- MuseTalk — talking head / lip sync
- Wan2.2 — text-to-video and image-to-video (use the variant that fits a 48GB L40S; prefer the 14B model with memory optimizations, fall back to TI2V-5B if VRAM-constrained)

---

## Critical Architecture Requirements

These are non-negotiable and must be implemented exactly:

### 1. Sequential GPU Job Queue
- One GPU = one job at a time. All generation jobs (both talking-head and B-roll) go into a **single sequential queue**.
- Implement with an `asyncio.Queue` and a single background worker task in FastAPI. Do not use multiprocessing per request.
- If two jobs are submitted, the second waits. The status endpoint must reflect queue position (`"status": "queued", "position": 2`).
- The worker must be crash-safe: if a job raises, mark it `"failed"` with an error message and continue to the next job. Never let one failed job kill the worker loop.

### 2. Models Stay Loaded
- Load model weights **once at startup** (or lazily on first use), then keep them in memory between jobs.
- Never load checkpoints from disk per request.
- Because Wan2.2 + MuseTalk + Fish Audio S2 Pro may not all fit in VRAM simultaneously, implement a simple **model manager**: keep the most recently used pipeline on GPU; when a job needs a different pipeline and VRAM is insufficient, offload the idle pipeline to CPU RAM (or free it) before loading the needed one. Log every load/offload event. (On the 48GB L40S all three normally fit resident — offloading is the safety valve, not the steady state.)

### 3. Job Lifecycle
- UUID job IDs.
- Job states: `queued` → `processing` (with `progress` 0–100) → `finished` | `failed`.
- Outputs saved to `backend/outputs/{jobId}/` and served as static files.
- Automatic folder creation on startup.

---

## API Specification

### POST /api/talking-head
Multipart form: `avatar` (image file), `script` (text), `voice` (string).
Response: `{ "jobId": "<uuid>" }`

### POST /api/broll
Multipart form: `prompt` (text), `image` (optional file), `duration` (3–5, seconds).
Response: `{ "jobId": "<uuid>" }`

### GET /api/status/{jobId}
Responses:
```json
{ "status": "queued", "position": 1 }
{ "status": "processing", "progress": 62, "stage": "lip-sync" }
{ "status": "finished", "video": "/outputs/<jobId>/output.mp4", "audio": "/outputs/<jobId>/speech.wav" }
{ "status": "failed", "error": "message" }
```
(B-roll jobs return only `video`; talking-head jobs return `video` and `audio`.)

### GET /api/jobs
Return recent jobs with status — used for a small "recent generations" list on both pages.

Input validation: file type, file size limits, script length limit, prompt length limit. Return 422 with clear messages on invalid input.

---

## Processing Pipelines

**Talking Head:**
1. Validate and save avatar image.
2. Generate `speech.wav` with Fish Audio S2 Pro (voice cloned from the selected preset's reference clip; correct language handling).
3. Run MuseTalk to animate the avatar against the audio.
4. Mux final `output.mp4` with FFmpeg (H.264 + AAC, faststart flag for browser playback).
5. Report progress at each stage.

**B-Roll:**
1. Validate prompt (and image if provided).
2. Run Wan2.2 text-to-video, or image-to-video when an image is supplied.
3. Encode to `output.mp4` (H.264, correct pixel format for Premiere Pro compatibility: `yuv420p`).
4. Report progress from the diffusion step callback (map denoising steps to 0–100).

---

## Frontend

Modern, minimal, responsive. Shared layout with top navigation between the two pages.

**Page 1 — /talking-head**
- Title, avatar upload with preview, voice selector, large script textarea, Generate button
- Progress indicator with stage label (queued / generating speech / lip sync / encoding)
- Video preview, audio preview
- Download Video and Download Audio buttons

**Page 2 — /broll**
- Prompt textarea, optional image upload with preview, duration selector (3–5s), Generate button
- Progress indicator showing queue position and generation progress
- Video preview and Download button
- Recent clips grid (last N generations) so batches can be queued and collected later — this matters because each clip takes several minutes

Poll `/api/status/{jobId}` every 2 seconds. Handle failed states gracefully with the error message shown to the user.

---

## Project Structure

```
project/
  frontend/
    app/
    components/
    lib/
    types/
    Dockerfile
  backend/
    app/            # FastAPI app, routes, queue, model manager
    models/         # downloaded checkpoints (gitignored)
    outputs/
    assets/
    scripts/        # model download scripts
    Dockerfile
  docker-compose.yml
  README.md
```

- Environment variables via `.env` (ports, model paths, output dir, max upload size).
- Proper structured logging throughout.
- Python type hints, TypeScript types, modular architecture, dependency injection where appropriate.

---

## Docker

- Backend Dockerfile: CUDA base image, PyTorch, FFmpeg, all model dependencies.
- Frontend Dockerfile: multi-stage Node build.
- `docker-compose.yml` with GPU passthrough (`deploy.resources.reservations.devices` / `gpus: all`) — `docker compose up` starts everything.
- Model weights are downloaded by `scripts/download_models.sh` into a mounted volume, not baked into the image.

---

## AWS Deployment (target: g6e.xlarge)

Provide complete step-by-step instructions in the README for:

- **Instance: g6e.xlarge (1× NVIDIA L40S, 48GB VRAM)** — primary target. Mention g6e.2xlarge as an upgrade if CPU/RAM becomes the bottleneck. Do NOT recommend multi-GPU instances for this MVP.
- Ubuntu 22.04 setup, NVIDIA driver + CUDA installation (or use the AWS Deep Learning AMI to skip manual driver setup — document both paths)
- Docker + NVIDIA Container Toolkit
- Model download (with expected disk sizes; provision a 300GB+ gp3 EBS volume)
- Nginx reverse proxy + SSL (Let's Encrypt), security group configuration (only 22/80/443 open)
- Startup on reboot (systemd unit or docker restart policy)
- **Stop/start workflow**: document that the instance should be stopped when not in use, that files persist across stop/start, and that the public IP changes on restart unless an Elastic IP is attached (recommend attaching one)

---

## README Must Cover

- Installation, local development, Docker deployment, AWS deployment
- Troubleshooting (CUDA errors, OOM, model download failures)
- GPU and VRAM requirements per model
- **Honest expected generation speed**: talking head ≈ 1–3 min per minute of script; Wan2.2 B-roll ≈ 3–8 min per 5-second clip on an L40S. Set expectations in the UI too.

---

## Code Quality

- Production-ready error handling everywhere
- No TODOs, no placeholders, no mock data
- Comments only where genuinely useful
- The app must be deployable immediately after running the model download script

Think carefully about the model manager and queue before writing code — they are the heart of this system.
