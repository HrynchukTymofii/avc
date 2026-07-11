# AI Video Studio — Architecture

Design document for the MVP described in `AI_Video_Studio_MVP_Plan.md`. No implementation code lives here — this is the blueprint the implementation stages will follow.

## Model stack at a glance

| Role | Model | Runs as |
|---|---|---|
| Voiceover (text-to-speech, voice cloning) | **Fish Audio S2 Pro** (self-hosted open weights) | GPU pipeline `s2_pipeline.py` |
| Talking head (lip-sync animation) | **MuseTalk 1.5** | GPU pipeline `musetalk_pipeline.py` |
| B-roll (text/image-to-video) | **Wan2.2 TI2V-5B** | GPU pipeline `wan_pipeline.py` |
| Still images (text-to-image) | **Wan2.2 TI2V-5B**, single frame (`num_frames=1`) | same `wan_pipeline.py`, `generate_image()` |

A talking-head job uses S2 Pro **then** MuseTalk (speech first, then lip-sync against the audio); B-roll and image jobs use Wan2.2 only. All pipelines are managed by the same model manager (section 3) and fed by the same sequential queue (section 2).

## Roadmap — candidate models (researched, not built)

The pipeline manager / job-kind pattern is the extension point: each of these is a new `ManagedPipeline` + processor + route + page, exactly like the image generator was added on top of Wan.

| Goal | Candidate | Why / constraints |
|---|---|---|
| Talking head **with head & body motion**, premium tier | **Wan2.2-S2V-14B** (official, HF `Wan-AI/Wan2.2-S2V-14B`, Apache 2.0) | Photo + audio → fully speech-driven avatar video. 14B dense ≈ 28 GB bf16 — tight on the 44 GB L40S and diffusion-per-frame makes long scripts prohibitive there (~30–90 min GPU per minute of audio), so **decided 2026-07-11: build this on the H100 tier, not the L40S**. The everyday path is the built-in hybrid (`animate` flag: Wan idle clip + MuseTalk lip-sync), which scales to 20-min scripts. |
| Animate a character image from a **driving video** | **Wan2.2-Animate-14B** (official, Apache 2.0) | Alternative/simpler path to head motion: record a short driving clip once, reuse per avatar. Same 14B sizing caveat. |
| Higher-quality B-roll (fixes 5B motion artifacts: morphing limbs/faces) | **Wan2.2 T2V/I2V-A14B** (MoE, two 14B experts) | Needs ~80 GB VRAM in bf16. Not an L40S model. |
| Higher-quality stills (text rendering, faces, fine detail) | **FLUX.1-dev** | ~24 GB bf16, fits the L40S; license is non-commercial (check before any paid service). |

**GPU tiers:** the L40S (g6e.2xlarge, ≈$2.3/h) stays the everyday tier and runs everything currently built. The 14B/A14B roadmap models want a single **H100 80 GB** — AWS P-family (separate quota, starts at 0, ≈$4+/h) or per-hour rentals (RunPod/Lambda). Treat H100 hours as a "quality tier" for batches, keep the cost model stop-when-idle.

**Versions beyond Wan 2.2:** Wan 2.5/2.6/2.7 are API-only (Alibaba's hosted platform) — no open weights as of 2026-07. Anything on HF claiming otherwise is a community re-upload; the official `Wan-AI` org is the source of truth.

**Licensing gate for any public/paid service:** S2 Pro is research-license (non-commercial); FLUX.1-dev likewise; MuseTalk needs a license review. Wan 2.2 family is Apache 2.0 throughout.

## Decisions locked in (from planning Q&A)

| Decision | Choice |
|---|---|
| TTS engine | **Fish Audio S2 Pro, self-hosted** (open weights: `huggingface.co/fishaudio/s2-pro`, inference via the `fish-speech` repo) — *changed from the original Fish Speech*. ~4.4B params (4B Slow-AR + 400M Fast-AR), ≈10 GB VRAM in bf16. Runs **in-process as a third managed GPU pipeline** (plain PyTorch inference, not the standalone SGLang server — a separate server would pin VRAM permanently and defeat the model manager). Voice cloning from a 10–30 s reference clip, no transcript needed. License: Fish Audio Research License — free for non-commercial use, which covers this project (hobby videos). |
| Wan2.2 variant | **TI2V-5B** as the default (one checkpoint does both T2V and I2V, fits comfortably in 48GB VRAM). The A14B path is documented in the README but not built. |
| Job persistence | **In-memory queue + per-job `status.json` on disk.** The live queue is an `asyncio.Queue` exactly as the plan requires; every state change also snapshots to `outputs/{jobId}/status.json`. On restart the queue is empty, but finished/failed history is rehydrated for `/api/jobs`, and any job that was `queued`/`processing` at crash time is rewritten as `failed: "server restarted"`. |
| Access protection | **Nginx basic auth** at the reverse proxy. Zero application code; documented in the deployment section of the README and shipped as an example config in `deploy/`. |
| Public access | **Subdomain on the user's existing domain** (e.g. `studio.<domain>`), added as a plain **A record in Vercel DNS → Elastic IP** (not attached to a Vercel project — Vercel only resolves the name; all hosting is on the AWS instance). Nginx terminates HTTPS with a free auto-renewing Let's Encrypt certificate (certbot) + basic auth. Security group opens only 22/80/443. SSH tunnel (`ssh -L 3000:localhost:3000`) documented in the README as a zero-exposure fallback for initial testing. |

Consequence: the model manager juggles **three** GPU pipelines (S2 Pro ≈ 10 GB, MuseTalk ≈ 6 GB, Wan TI2V-5B ≈ 18–22 GB peak). All three resident total ≈ 34 GB, which still fits the 48GB L40S with headroom for Wan's activation spikes — so offloading remains a safety valve rather than a per-job event, but it is implemented fully (it is what makes the system portable to 24GB cards).

Remaining config item for implementation time: `assets/voices/` must contain real reference clips — one 10–30 s WAV per preset voice (clean single-speaker audio; no transcript needed for S2). This is deployment content, not a code placeholder.

---

## 1. Project structure

```
AVC/
├── AI_Video_Studio_MVP_Plan.md        # Original product/requirements plan
├── ARCHITECTURE.md                    # This document
├── README.md                          # Install, local dev, Docker, AWS deployment, troubleshooting
├── docker-compose.yml                 # frontend + backend services, GPU passthrough, volume mounts
├── .env.example                       # Every env var with a sane default and a comment
├── .gitignore                         # node_modules, model weights, outputs, .env, __pycache__
│
├── deploy/
│   ├── nginx.conf.example             # Reverse proxy: / → frontend, /api + /outputs → backend, basic auth, 100MB client_max_body_size
│   └── ai-video-studio.service        # systemd unit: docker compose up -d on boot
│
├── frontend/
│   ├── Dockerfile                     # Multi-stage: deps → build → slim node runner (standalone output)
│   ├── package.json                   # Next 15, React, Tailwind, shadcn/ui deps
│   ├── next.config.ts                 # standalone output; /api/* and /outputs/* rewrites → BACKEND_URL (dev + compose)
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   ├── components.json                # shadcn/ui config
│   ├── app/
│   │   ├── layout.tsx                 # Root layout: font, <NavBar/>, Tailwind globals, metadata
│   │   ├── globals.css                # Tailwind base + shadcn CSS variables (light/dark)
│   │   ├── page.tsx                   # Redirects / → /talking-head
│   │   ├── talking-head/
│   │   │   └── page.tsx               # Page 1: avatar upload, voice select, script, generate, progress, previews, downloads
│   │   └── broll/
│   │       └── page.tsx               # Page 2: prompt, optional image, duration, generate, progress, recent-clips grid
│   ├── components/
│   │   ├── nav-bar.tsx                # Top navigation between the two tools
│   │   ├── file-dropzone.tsx          # Drag-and-drop image input with client-side type/size check + thumbnail preview
│   │   ├── job-progress.tsx           # Renders queued (position) / processing (progress bar + stage label) / failed (error alert)
│   │   ├── video-preview.tsx          # <video> player with poster + Download button
│   │   ├── recent-jobs.tsx            # Grid of recent finished jobs from GET /api/jobs (filterable by kind)
│   │   └── ui/                        # Generated shadcn/ui primitives: button, card, textarea, select,
│   │                                  #   progress, alert, badge, skeleton, label, slider
│   ├── lib/
│   │   ├── api.ts                     # Typed fetch client: submitTalkingHead, submitBroll, getStatus, getJobs, getVoices
│   │   ├── use-job-polling.ts         # Hook: polls /api/status/{id} every 2s until finished/failed; exposes JobStatus
│   │   └── utils.ts                   # cn() class merger (shadcn)
│   └── types/
│       └── api.ts                     # TS mirrors of every backend schema (section 4)
│
└── backend/
    ├── Dockerfile                     # nvidia/cuda runtime base, Python 3.11, PyTorch cu121, FFmpeg, app deps
    ├── requirements.txt               # fastapi, uvicorn, pydantic-settings, torch, diffusers, transformers, accelerate,
    │                                  #   fish-speech (S2 inference), MuseTalk deps (opencv, mmpose/dwpose, librosa),
    │                                  #   soundfile, pillow, python-multipart
    ├── .dockerignore
    ├── app/
    │   ├── __init__.py
    │   ├── main.py                    # App factory: settings, logging, dirs, static /outputs mount, routers,
    │   │                              #   lifespan (rehydrate job store → start worker → shutdown cleanly)
    │   ├── config.py                  # Settings (pydantic-settings): ports, paths, limits, Fish Audio creds, VRAM budgets
    │   ├── logging_config.py          # Structured logging (JSON in prod, pretty in dev); uvicorn logger integration
    │   ├── schemas.py                 # All Pydantic request/response models (section 4)
    │   ├── deps.py                    # FastAPI dependency providers: get_store, get_worker, get_voice_registry
    │   ├── routes/
    │   │   ├── __init__.py
    │   │   ├── generation.py          # POST /api/talking-head, POST /api/broll (multipart validation → save inputs → enqueue)
    │   │   ├── status.py              # GET /api/status/{job_id}, GET /api/jobs
    │   │   └── voices.py              # GET /api/voices (from assets/voices.json)
    │   ├── queue/
    │   │   ├── __init__.py
    │   │   ├── job.py                 # Job dataclass, JobState/JobKind enums, param dataclasses (section 2)
    │   │   ├── job_store.py           # In-memory registry + status.json snapshots + startup rehydration
    │   │   └── worker.py              # GPUWorker: asyncio.Queue, single loop, crash isolation, timeout (section 2)
    │   ├── pipelines/
    │   │   ├── __init__.py
    │   │   ├── base.py                # ManagedPipeline ABC + PipelineState enum (section 3)
    │   │   ├── manager.py             # ModelManager: GPU residency, LRU offload, VRAM accounting, event logging
    │   │   ├── s2_pipeline.py         # Fish Audio S2 Pro wrapper: in-process fish-speech inference, ref-audio voice cloning
    │   │   ├── musetalk_pipeline.py   # MuseTalk wrapper: load once, preprocess avatar, run lip-sync inference
    │   │   └── wan_pipeline.py        # Wan2.2 TI2V-5B wrapper: shared components behind T2V + I2V entry points
    │   └── services/
    │       ├── __init__.py
    │       ├── talking_head.py        # TalkingHeadProcessor: TTS → MuseTalk → FFmpeg mux, staged progress
    │       ├── broll.py               # BrollProcessor: Wan2.2 (T2V/I2V) → FFmpeg encode, step-callback progress
    │       ├── ffmpeg.py              # Async subprocess helpers: mux_av(), encode_h264() — H.264/AAC, yuv420p, +faststart
    │       ├── validation.py          # Upload guards: extension + magic-byte sniff (Pillow), size limit, text length
    │       └── voices.py              # VoiceRegistry: loads/validates assets/voices.json + reference clips at startup
    ├── assets/
    │   ├── voices.json                # Curated voice presets: [{id, name, language, ref_audio}]
    │   └── voices/                    # One 10–30 s reference WAV per preset (clean single-speaker audio)
    ├── models/                        # Downloaded checkpoints (gitignored, volume-mounted)
    │   ├── s2-pro/                    # Fish Audio S2 Pro weights (huggingface.co/fishaudio/s2-pro, ~10 GB)
    │   ├── musetalk/                  # MuseTalk 1.5 UNet + whisper-tiny + sd-vae-ft-mse + dwpose + face-parse weights
    │   └── wan2.2-ti2v-5b/            # Wan2.2 TI2V-5B diffusers checkpoint (transformer, VAE, UMT5 text encoder)
    ├── outputs/                       # {jobId}/ → status.json, inputs/, speech.wav, output.mp4 (gitignored, volume-mounted)
    ├── scripts/
    │   └── download_models.sh         # huggingface-cli downloads with resume, disk-size preflight, checksums
    └── tests/
        ├── __init__.py
        ├── test_queue.py              # Worker: ordering, position reporting, crash isolation, timeout (fake processors)
        ├── test_model_manager.py      # Residency/eviction policy with dummy pipelines (no GPU needed)
        └── test_validation.py         # Upload/text validation edge cases
```

Naming note: GPU pipeline code lives in `app/pipelines/`, not `app/models/`, to avoid colliding with the `backend/models/` checkpoint directory from the plan.

---

## 2. Sequential GPU job queue

### 2.1 States and transitions

```
                submit                worker picks up            success
  (validated) ────────►  QUEUED  ────────────────────►  PROCESSING ────────►  FINISHED
                            │                                │
                            │ server restart                 │ exception / timeout / restart
                            ▼                                ▼
                          FAILED ◄───────────────────────  FAILED
```

- `QUEUED` — in the `asyncio.Queue`, waiting. Status responses include `position`.
- `PROCESSING` — the single worker is executing it. Carries `progress: 0–100` and a `stage` string (`"tts"`, `"lip-sync"`, `"encoding"` for talking-head; `"diffusion"`, `"encoding"` for B-roll). The frontend maps stage keys to human labels.
- `FINISHED` — terminal. Carries output URLs (`video`, and `audio` for talking-head).
- `FAILED` — terminal. Carries a user-presentable `error` message (the raw traceback goes to logs only).

There is no cancel state in the MVP; the state machine leaves room to add one later.

### 2.2 Data structures

```python
class JobKind(str, Enum):
    TALKING_HEAD = "talking_head"
    BROLL = "broll"

class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    FINISHED = "finished"
    FAILED = "failed"

@dataclass
class TalkingHeadParams:
    avatar_path: Path          # saved under outputs/{jobId}/inputs/ before enqueue
    script: str
    voice_id: str              # key into VoiceRegistry

@dataclass
class BrollParams:
    prompt: str
    duration_s: int            # 3–5
    image_path: Path | None    # I2V when present, T2V otherwise

@dataclass
class Job:
    id: str                                    # uuid4 hex-with-dashes
    kind: JobKind
    params: TalkingHeadParams | BrollParams
    state: JobState = JobState.QUEUED
    progress: int = 0                          # 0–100, only meaningful while PROCESSING
    stage: str | None = None
    error: str | None = None
    outputs: dict[str, str] = field(default_factory=dict)   # {"video": "/outputs/.../output.mp4", "audio": ...}
    label: str = ""                            # short display text: script/prompt excerpt for the recent-jobs list
    created_at: datetime = ...
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

**`JobStore`** — the single source of truth for job state:

```python
class JobStore:
    def __init__(self, outputs_dir: Path) -> None: ...
    def add(self, job: Job) -> None
    def get(self, job_id: str) -> Job | None
    def list_recent(self, limit: int = 20, kind: JobKind | None = None) -> list[Job]
    def queued_position(self, job_id: str) -> int | None        # 1-based index among QUEUED jobs by created_at
    def update(self, job_id: str, **changes: Any) -> Job        # mutate + persist snapshot
    def rehydrate(self) -> None                                 # startup: scan outputs/*/status.json
    def _persist(self, job: Job) -> None                        # write status.json atomically (tmp + rename)
```

All mutation happens on the event loop (routes and worker both run there), so a plain `dict[str, Job]` needs no locking. `_persist` writes are tiny (<1 KB) and atomic via write-to-temp-then-rename; progress snapshots are throttled to at most one write per second per job so diffusion callbacks don't hammer the disk.

**Queue position** is never stored — it is computed at read time as the job's 1-based index among all `QUEUED` jobs ordered by `created_at`. This makes positions self-consistent by construction: when the worker takes a job, everyone behind it moves up automatically, with no renumbering pass. (A job that has moved to `PROCESSING` reports `progress`, not a position.)

### 2.3 The worker loop

```python
class JobProcessor(Protocol):
    async def process(self, job: Job, report: ProgressReporter) -> dict[str, str]:
        """Run the job; return the outputs dict. Raises on failure."""

ProgressReporter = Callable[[int, str], None]   # (progress_pct, stage) → updates store

class GPUWorker:
    def __init__(
        self,
        store: JobStore,
        processors: Mapping[JobKind, JobProcessor],
        job_timeout_s: float,
    ) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()     # job IDs only; state lives in the store
        self._task: asyncio.Task[None] | None = None
        self.current_job_id: str | None = None

    async def submit(self, job: Job) -> None                  # store.add + queue.put_nowait
    def start(self) -> None                                   # called from FastAPI lifespan startup
    async def stop(self) -> None                              # cancel task, mark in-flight job failed, drain
    async def _run(self) -> None                              # the single forever-loop
    async def _process_one(self, job_id: str) -> None
```

The loop, in prose:

1. `job_id = await self._queue.get()` — sleeps until work arrives.
2. Look the job up in the store. If missing (shouldn't happen), log and continue.
3. Set `state=PROCESSING`, `started_at`, `current_job_id`; log job start with kind and label.
4. Run `await asyncio.wait_for(processor.process(job, report), timeout=job_timeout_s)`. The timeout (default 30 min, env-configurable) guarantees a hung model call cannot block the queue forever.
5. On success: `state=FINISHED`, store the outputs dict, log duration.
6. On failure — the crash-safety core:

```python
try:
    outputs = await asyncio.wait_for(processor.process(job, report), self._job_timeout_s)
    self._store.update(job.id, state=JobState.FINISHED, outputs=outputs, ...)
except asyncio.CancelledError:
    self._store.update(job.id, state=JobState.FAILED, error="Server shut down during processing")
    raise                                # shutdown must propagate — never swallow CancelledError
except asyncio.TimeoutError:
    self._store.update(job.id, state=JobState.FAILED, error=f"Job exceeded {timeout} time limit")
except Exception as exc:                 # any job error: isolate, record, continue
    log.exception("job failed", job_id=job.id)
    self._store.update(job.id, state=JobState.FAILED, error=user_message(exc))
finally:
    self.current_job_id = None
    self._queue.task_done()
```

The `while True` loop wraps `_process_one` so only `CancelledError` can exit it. A failed job therefore never kills the worker: the exception is converted into job state, CUDA state is cleaned up, and the loop immediately `get()`s the next job.

**Post-failure GPU hygiene:** after any failure the worker calls `model_manager.after_job_failure()` (section 3), which runs `torch.cuda.empty_cache()` and — if the failure was a CUDA OOM — offloads every resident pipeline so the next job starts from a clean slate. This is what makes "one bad job" not poison job N+1.

**Keeping the event loop responsive:** processors are `async`, but the actual model inference is synchronous CUDA work. Each processor runs its heavy calls via `asyncio.to_thread(...)` on a dedicated single worker thread, so status polling, uploads, and static file serving stay responsive during a 5-minute diffusion run. Progress callbacks fire on that worker thread and hand off to the loop with `loop.call_soon_threadsafe(report, pct, stage)` — the store is only ever touched from the event loop.

**Why IDs in the queue, not Job objects:** the store is the single source of truth. If a job's state was mutated between enqueue and dequeue (e.g. marked failed during shutdown persistence), the worker sees current reality, not a stale snapshot.

### 2.4 Startup / shutdown

- **Startup (FastAPI lifespan):** create `outputs/` and per-config dirs → `store.rehydrate()` (load history; convert stale `queued`/`processing` records to `failed: "server restarted"`) → construct ModelManager and processors → `worker.start()`.
- **Shutdown:** `worker.stop()` cancels the task; the in-flight job is marked failed with a clear message; ModelManager releases GPU memory. Uvicorn's graceful shutdown window covers this.

---

## 3. Model manager

### 3.1 What it manages

Three pipelines touch the GPU:

| Pipeline | Weights on GPU (bf16/fp16) | Peak with activations | Load-from-disk time |
|---|---|---|---|
| Fish Audio S2 Pro (4B Slow-AR + 400M Fast-AR + RVQ codec, via fish-speech) | ~9–10 GB | ~12 GB | ~30 s |
| MuseTalk (UNet + whisper-tiny + SD-VAE + dwpose + face-parse) | ~5–6 GB | ~8 GB | ~15 s |
| Wan2.2 TI2V-5B (DiT + Wan-VAE + UMT5-XXL encoder) | ~17–19 GB | ~22–26 GB during denoising/VAE decode | ~60–90 s |

All three resident ≈ 34 GB of weights; the worst single-job peak (Wan denoising at ~26 GB with S2 + MuseTalk idle-resident at ~16 GB) ≈ 42 GB < 48 GB. So on the L40S **all pipelines normally stay resident and offloading rarely fires**. The manager still implements eviction fully, because (a) VAE decode spikes are workload-dependent, (b) it makes the system portable to 24GB cards, and (c) the plan requires it. Eviction is driven by *measured* free VRAM (`torch.cuda.mem_get_info`), not just static estimates.

**Offload target:** per-pipeline policy, env-configurable. S2 Pro (~10 GB) and MuseTalk (~6 GB) default to `cpu` — cheap to bring back. Wan defaults to `cpu` as well (~17 GB), with `unload` (free entirely, reload from disk next time) available as the fallback policy for RAM-constrained hosts. This dual policy exists because on g6e.xlarge system RAM (32 GB) is *smaller* than VRAM (48 GB): the worst realistic case (Wan on GPU, S2 + MuseTalk offloaded ≈ 16 GB CPU + ~4 GB app footprint) fits, but "offload all three to CPU" would not — the eviction loop therefore stops as soon as headroom is reached and never offloads more than it must.

### 3.2 Residency model

Each pipeline is a state machine owned by the manager:

```
UNLOADED ──load()──► ON_CPU ──to_gpu()──► ON_GPU
    ▲                  │  ▲                  │
    └────unload()──────┘  └────to_cpu()──────┘
```

- Loading is **lazy on first use** (plan allows it): startup stays fast, and the first job of each kind pays the one-time load cost. Weights are then held for the life of the process — never re-read from disk unless the `unload` policy evicted them.
- Every transition emits a structured log line: `{"event": "pipeline_offload", "pipeline": "wan", "from": "ON_GPU", "to": "ON_CPU", "freed_gb": 17.2, "took_s": 4.1, "reason": "vram_needed_by=musetalk"}`.

### 3.3 Interface

```python
class PipelineState(str, Enum):
    UNLOADED = "unloaded"
    ON_CPU = "on_cpu"
    ON_GPU = "on_gpu"

class OffloadPolicy(str, Enum):
    CPU = "cpu"          # .to("cpu") — fast to restore, costs system RAM
    UNLOAD = "unload"    # free everything — slow to restore, costs nothing

class ManagedPipeline(ABC):
    """A lazily-loaded model pipeline whose device placement the ModelManager controls."""

    name: str
    vram_estimate_gb: float          # steady-state weights on GPU
    vram_peak_gb: float              # worst-case including activations — used for admission checks
    offload_policy: OffloadPolicy
    state: PipelineState
    last_used_at: float              # monotonic timestamp, maintained by the manager

    @abstractmethod
    def load(self) -> None:
        """Read checkpoints from disk into CPU memory. Idempotent. Blocking (runs in worker thread)."""

    @abstractmethod
    def to_gpu(self) -> None:
        """Move weights to CUDA. Requires state >= ON_CPU."""

    @abstractmethod
    def to_cpu(self) -> None:
        """Move weights to system RAM and torch.cuda.empty_cache()."""

    @abstractmethod
    def unload(self) -> None:
        """Drop all weights and free both CPU and GPU memory."""


class S2Pipeline(ManagedPipeline):
    """Fish Audio S2 Pro via in-process fish-speech inference (PyTorch path, not the
    SGLang server — a separate server process would pin VRAM outside the manager's control)."""

    def generate(
        self,
        text: str,
        reference_audio: Path,                     # 10–30 s voice clip; no transcript needed
        out_path: Path,                            # writes speech.wav (44.1 kHz mono WAV — MuseTalk-friendly)
        on_progress: Callable[[float], None],      # fraction of text chunks synthesized
    ) -> Path:
        """Synthesize the script in the cloned voice. Long scripts are chunked at sentence
        boundaries and concatenated, so progress is meaningful and memory stays bounded."""


class MuseTalkPipeline(ManagedPipeline):
    def generate(
        self,
        avatar_path: Path,
        audio_path: Path,
        out_path: Path,
        on_progress: Callable[[float], None],      # 0.0–1.0 fraction of frames rendered
    ) -> Path:
        """Lip-sync the avatar to the audio; writes a raw video (no audio track) to out_path."""


class WanPipeline(ManagedPipeline):
    """Wraps Wan2.2 TI2V-5B. T2V and I2V share the transformer/VAE/text-encoder,
    exposed as two diffusers pipeline views over the same components."""

    def generate(
        self,
        prompt: str,
        duration_s: int,                            # 3–5 → frame count = duration * 24, snapped to 4k+1
        image_path: Path | None,                    # switches T2V → I2V
        out_path: Path,
        on_progress: Callable[[float], None],       # denoising step i/total from the diffusers callback
        seed: int | None = None,
    ) -> Path:
        """Generate the clip and write raw frames to out_path (final encode is the service's job)."""


class ModelManager:
    """Owns GPU residency. The worker acquires a pipeline per job; the manager guarantees
    it is ON_GPU with enough free VRAM before yielding it, evicting idle pipelines LRU-first."""

    def __init__(self, pipelines: Sequence[ManagedPipeline], settings: Settings) -> None: ...

    @asynccontextmanager
    async def acquire(self, name: str) -> AsyncIterator[ManagedPipeline]:
        """Ensure `name` is loaded and ON_GPU, then yield it. Serialised by an internal
        asyncio.Lock (defense in depth — the single worker is already sequential).
        Blocking load/move work runs via asyncio.to_thread."""

    def free_vram_gb(self) -> float:
        """Measured free VRAM from torch.cuda.mem_get_info."""

    async def after_job_failure(self, *, oom: bool) -> None:
        """empty_cache(); on OOM additionally offload every resident pipeline."""

    async def shutdown(self) -> None:
        """Unload everything (called from lifespan shutdown)."""

    # internal
    async def _ensure_headroom(self, needed_gb: float, keep: str) -> None:
        """While free VRAM < needed_gb: offload the least-recently-used ON_GPU pipeline
        (except `keep`) per its policy. Raises InsufficientVRAMError if nothing left to evict."""
```

### 3.4 Acquisition flow (what happens per job)

```
worker → manager.acquire("wan")
  1. lock
  2. if wan.state == UNLOADED: to_thread(wan.load())            # first use only
  3. headroom check: free_vram >= wan.vram_peak_gb + reserve (2 GB)?
       no → offload LRU ON_GPU pipeline (musetalk → cpu), re-check
  4. if wan.state != ON_GPU: to_thread(wan.to_gpu())
  5. touch last_used_at; yield wan
  6. on exit: nothing is moved — the pipeline stays ON_GPU for the next job (MRU stays hot)
```

Step 6 is the "keep the most recently used pipeline on GPU" requirement: eviction only ever happens *on demand* from step 3, never eagerly. Alternating talking-head/B-roll jobs on the L40S settle into both pipelines resident with zero moves.

### 3.5 Acquisition order for talking-head jobs

A talking-head job needs S2 Pro first, then MuseTalk. The processor acquires them **sequentially, not nested**: `acquire("s2")` → synthesize → release → `acquire("musetalk")` → animate. Sequential acquisition means the headroom check only ever has to satisfy one active pipeline's peak at a time, and on a 48GB card both simply stay resident between the two steps (release moves nothing — see step 6 above).

**License note (S2 Pro):** the open weights ship under the Fish Audio Research License — free for non-commercial use, which covers this project's hobby-video use case. Should that ever change, `S2Pipeline` is the only code that touches the model, and its `generate()` signature deliberately matches what a hosted-API client would expose, so swapping to the commercially-licensed Fish Audio API is a one-file change.

---

## 4. API schemas

### 4.1 Pydantic models (backend `app/schemas.py`)

Multipart request fields arrive as FastAPI `Form(...)`/`File(...)` parameters; the constraints below are enforced in the route via these models and `services/validation.py` (magic-byte sniffing, streamed size limit). All violations return **422** with a human-readable `detail`.

```python
# ---- shared -------------------------------------------------------------

class JobKind(str, Enum):
    TALKING_HEAD = "talking_head"
    BROLL = "broll"

class JobCreatedResponse(BaseModel):
    job_id: str = Field(serialization_alias="jobId")

class ErrorResponse(BaseModel):
    detail: str

# ---- request constraints (validated from multipart forms) ---------------

class TalkingHeadRequest(BaseModel):
    script: str = Field(min_length=1, max_length=5_000, description="Whitespace-stripped")
    voice: str                                  # must exist in VoiceRegistry → 422 otherwise
    # avatar: UploadFile — PNG/JPEG by magic bytes, <= MAX_UPLOAD_MB (default 20)

class BrollRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000)
    duration: int = Field(ge=3, le=5)
    # image: UploadFile | None — same image rules as avatar

# ---- status: discriminated union on `status` ----------------------------

class QueuedStatus(BaseModel):
    status: Literal["queued"] = "queued"
    position: int                               # 1-based

class ProcessingStatus(BaseModel):
    status: Literal["processing"] = "processing"
    progress: int = Field(ge=0, le=100)
    stage: str                                  # "tts" | "lip-sync" | "encoding" | "diffusion"

class FinishedStatus(BaseModel):
    status: Literal["finished"] = "finished"
    video: str                                  # "/outputs/{jobId}/output.mp4"
    audio: str | None = None                    # talking-head only; omitted (not null) for B-roll

class FailedStatus(BaseModel):
    status: Literal["failed"] = "failed"
    error: str

StatusResponse = Annotated[
    QueuedStatus | ProcessingStatus | FinishedStatus | FailedStatus,
    Field(discriminator="status"),
]

# ---- job list ------------------------------------------------------------

class JobSummary(BaseModel):
    job_id: str = Field(serialization_alias="jobId")
    kind: JobKind
    status: Literal["queued", "processing", "finished", "failed"]
    label: str                                  # script/prompt excerpt for display
    created_at: datetime = Field(serialization_alias="createdAt")
    video: str | None = None                    # present when finished
    audio: str | None = None

class JobListResponse(BaseModel):
    jobs: list[JobSummary]

# ---- voices ---------------------------------------------------------------

class Voice(BaseModel):
    id: str                                     # our stable key, e.g. "en-female-warm"
    name: str                                   # display name
    language: str                               # BCP-47-ish: "en", "hu", ...
    ref_audio: Path = Field(exclude=True)       # assets/voices/*.wav reference clip — never leaves the backend

class VoicesResponse(BaseModel):
    voices: list[Voice]
```

Endpoint → schema map:

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/talking-head` | multipart → `TalkingHeadRequest` + avatar file | `JobCreatedResponse` / 422 `ErrorResponse` |
| `POST /api/broll` | multipart → `BrollRequest` + optional image | `JobCreatedResponse` / 422 `ErrorResponse` |
| `GET /api/status/{jobId}` | — | `StatusResponse` / 404 `ErrorResponse` |
| `GET /api/jobs?kind=&limit=` | — | `JobListResponse` |
| `GET /api/voices` | — | `VoicesResponse` |
| `GET /outputs/{jobId}/...` | — | static files (StaticFiles mount) |

### 4.2 TypeScript types (`frontend/types/api.ts`)

```typescript
export type JobKind = "talking_head" | "broll";

export interface JobCreatedResponse {
  jobId: string;
}

export type JobStatus =
  | { status: "queued"; position: number }
  | { status: "processing"; progress: number; stage: Stage }
  | { status: "finished"; video: string; audio?: string }
  | { status: "failed"; error: string };

export type Stage = "tts" | "lip-sync" | "encoding" | "diffusion";

export const STAGE_LABELS: Record<Stage, string> = {
  tts: "Generating speech",
  "lip-sync": "Animating avatar",
  diffusion: "Generating video",
  encoding: "Encoding video",
};

export interface JobSummary {
  jobId: string;
  kind: JobKind;
  status: "queued" | "processing" | "finished" | "failed";
  label: string;
  createdAt: string;            // ISO 8601
  video?: string;
  audio?: string;
}

export interface JobListResponse {
  jobs: JobSummary[];
}

export interface Voice {
  id: string;
  name: string;
  language: string;
}

export interface VoicesResponse {
  voices: Voice[];
}

export interface ApiError {
  detail: string;
}
```

The discriminated `JobStatus` union means the polling hook and `job-progress.tsx` get exhaustive `switch (status.status)` narrowing — the compiler enforces that every state renders something.

### 4.3 Key environment variables (`.env.example`)

```
BACKEND_PORT=8000                 FRONTEND_PORT=3000
BACKEND_URL=http://backend:8000   # Next.js rewrite target inside compose
MODELS_DIR=./models               OUTPUTS_DIR=./outputs
MAX_UPLOAD_MB=20                  MAX_SCRIPT_CHARS=5000        MAX_PROMPT_CHARS=1000
JOB_TIMEOUT_S=1800                RECENT_JOBS_LIMIT=20
WAN_VARIANT=ti2v-5b               VRAM_RESERVE_GB=2
S2_OFFLOAD=cpu                    MUSETALK_OFFLOAD=cpu         WAN_OFFLOAD=cpu   # cpu | unload
LOG_FORMAT=pretty                 # pretty | json
```

---

## 5. Build order

Each stage leaves the repo in a runnable state; GPU-dependent stages are separated from everything testable on this Windows machine.

**Stage 1 — Backend skeleton (no GPU)**
1. `backend/app/config.py` — Settings
2. `backend/app/logging_config.py`
3. `backend/app/schemas.py` — all models from section 4
4. `backend/app/services/validation.py`
5. `backend/app/main.py` — app factory, lifespan shell, static mount, health check
6. `backend/requirements.txt`, `.env.example`, `.gitignore`

**Stage 2 — Queue core (no GPU; the heart of the system, fully unit-tested before any model code exists)**
7. `backend/app/queue/job.py`
8. `backend/app/queue/job_store.py`
9. `backend/app/queue/worker.py`
10. `backend/app/deps.py`
11. `backend/app/routes/status.py` — status + jobs endpoints
12. `backend/tests/test_queue.py`, `backend/tests/test_validation.py` — run with fake sleep-processors: verify ordering, positions, crash isolation, timeout, restart rehydration

**Stage 3 — Voices (no GPU)**
13. `backend/app/services/voices.py` + `backend/assets/voices.json` + `backend/assets/voices/*.wav` (curated 10–30 s reference clips)
14. `backend/app/routes/voices.py`

**Stage 4 — Model manager (logic testable without GPU via dummy pipelines)**
15. `backend/app/pipelines/base.py`
16. `backend/app/pipelines/manager.py`
17. `backend/tests/test_model_manager.py`

**Stage 5 — Pipelines + services + generation routes (GPU; developed against the L40S instance)**
18. `backend/app/services/ffmpeg.py`
19. `backend/app/pipelines/s2_pipeline.py`
20. `backend/app/pipelines/musetalk_pipeline.py`
21. `backend/app/services/talking_head.py`
22. `backend/app/pipelines/wan_pipeline.py`
23. `backend/app/services/broll.py`
24. `backend/app/routes/generation.py` — wire both POST endpoints to the worker
25. `backend/scripts/download_models.sh`

**Stage 6 — Frontend foundation**
26. `frontend/` scaffold: `package.json`, `next.config.ts`, `tsconfig.json`, Tailwind + shadcn setup, `app/layout.tsx`, `app/globals.css`, `app/page.tsx`
27. `frontend/types/api.ts`
28. `frontend/lib/api.ts`, `frontend/lib/use-job-polling.ts`, `frontend/lib/utils.ts`

**Stage 7 — Frontend UI**
29. `frontend/components/nav-bar.tsx`, `file-dropzone.tsx`, `job-progress.tsx`, `video-preview.tsx`, `recent-jobs.tsx` (+ shadcn `ui/` primitives as needed)
30. `frontend/app/talking-head/page.tsx`
31. `frontend/app/broll/page.tsx`

**Stage 8 — Packaging & deployment**
32. `backend/Dockerfile`, `backend/.dockerignore`
33. `frontend/Dockerfile`
34. `docker-compose.yml`
35. `deploy/nginx.conf.example`, `deploy/ai-video-studio.service`
36. `README.md` — install, local dev, Docker, full AWS g6e.xlarge walkthrough, troubleshooting, honest speed expectations

Dependency rationale: the queue (stage 2) is built and tested before any model code so its semantics are proven with cheap fake jobs; the model manager (stage 4) is likewise tested with dummy pipelines so the only untested-on-Windows code is the two pipeline wrappers themselves, which get exercised on the GPU instance in stage 5.
