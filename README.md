# AI Video Studio

A self-hosted web app with GPU generation tools sharing one backend, one
queue, and one GPU:

- **Talking Head Studio** — upload a portrait, pick a voice, paste a script →
  lip-synced talking-head video (Fish Audio **S2 Pro** voice cloning +
  **MuseTalk** lip-sync).
- **B-Roll Generator** — describe a shot (optionally from a reference image) →
  3–5 second clip (**Wan2.2 TI2V-5B**), encoded for Premiere Pro.
- **Full Video Studio** — one tagged script → one finished video: talking head
  on camera, AI b-roll, AI stills (slow zoom) and your own uploaded clips, cut
  together over a continuous voiceover.

Architecture details live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Writing scripts: voice emotion tags

The S2 voice model understands inline **square-bracket tags** in the script —
they are interpreted, not read aloud, and each tag affects the speech that
comes **after** it. Use a few per paragraph, not one per sentence.

- **Pauses & breath:** `[short pause]` `[pause]` `[long pause]` `[breath]`
  `[sigh]` `[inhale]`
- **Emotion:** `[excited]` `[sad]` `[angry]` `[surprised]` `[whisper]` — with
  intensity: `[slightly sad]`, `[very excited]`
- **Delivery:** `[emphasis]` `[low voice]` `[volume up]` `[laughing]`
  `[chuckle]` `[professional broadcast tone]`
- Free-form descriptions also work (open vocabulary), e.g.
  `[whisper in small voice]`, `[pitch up]`.

Example:

```
[professional broadcast tone] The future is closer than ever. [short pause]
Every breakthrough opens new possibilities... [emphasis] and the innovations
we build today [short pause] will shape future generations.
```

### Prompt block for LLM script writing

Paste this into Claude/ChatGPT together with your topic to get scripts that
arrive pre-tagged:

> Write a voiceover script for [TOPIC], about [N] minutes when spoken.
> Annotate it for an expressive TTS engine using inline square-bracket tags
> that affect the speech after them. Available tags: [short pause], [pause],
> [long pause], [breath], [sigh], [emphasis], [excited], [slightly excited],
> [sad], [surprised], [whisper], [low voice], [volume up], [laughing],
> [chuckle], and free-form delivery descriptions like [professional broadcast
> tone]. Rules: set the overall tone with one tag at the start; use at most
> 2–3 tags per paragraph; place each tag exactly where the delivery should
> change; prefer pauses and emphasis over strong emotions unless the content
> calls for them; never put a tag mid-word; output plain text only.

## Full Video: tagged scripts

Full Video Studio reads the same script format and adds **visual markers** that
direct the cut. The rule that keeps them apart from voice tags: **visual
markers contain a colon** (or are exactly `[ONCAMERA]`); anything else in
square brackets is a voice tag and gets spoken direction as usual.

| Marker | Effect |
|---|---|
| plain text | spoken on camera by your avatar (talking head) |
| `[BROLL: <prompt>]` | following text is voiced over an AI-generated clip (Wan2.2) |
| `[IMAGE: <prompt>]` | following text is voiced over an AI still with a slow Ken Burns zoom |
| `[CLIP: <filename>]` | following text is voiced over a clip you uploaded with the job (muted, trimmed/looped to fit) |
| `[ONCAMERA]` | return to the talking head |

A marker's segment lasts until the next marker. Keywords are case-insensitive
(`[b-roll: …]` and `[ON CAMERA]` also work). Segment videos are fitted to the
narration length automatically: short b-roll is ping-pong-looped, stills zoom
for exactly the narration duration, long clips are trimmed.

Example:

```
[professional broadcast tone] Welcome back to the channel.

[BROLL: aerial drone shot of a solar farm at sunset, golden light]
Across the world, solar capacity has tripled in a decade. [short pause]

[IMAGE: clean minimalist diagram of a photovoltaic cell]
Each cell converts photons into electron flow.

[CLIP: lab-tour.mp4]
Here is how we test the panels in our own lab.

[ONCAMERA]
[emphasis] And that is why the next ten years matter.
```

### Prompt block for LLM full-video scripts

Paste this into Claude/ChatGPT together with your topic:

> Write a voiceover script for [TOPIC], about [N] minutes when spoken, for a
> video that mixes an on-camera presenter with cutaway footage. Direct the
> visuals with markers on their own lines: `[BROLL: <detailed scene prompt>]`
> to cut to AI-generated footage, `[IMAGE: <detailed image prompt>]` for an AI
> still with a slow zoom, and `[ONCAMERA]` to return to the presenter. Plain
> text is spoken on camera. Open and close on camera; cut away every 2–4
> sentences; write b-roll/image prompts as rich visual descriptions (subject,
> setting, lighting, camera angle), never as narration. Keep using expressive
> voice tags like [short pause], [emphasis], [excited] inside the narration —
> but never put a colon inside a voice tag, colons are reserved for visual
> markers. Output plain text only.

## Honest speed expectations

On the target g6e.2xlarge (NVIDIA L40S, 48 GB VRAM, 64 GB RAM):

| Job | Time |
|---|---|
| Talking head | ≈ 1–3 minutes of processing **per minute of script** |
| B-roll clip (5 s, 704×1280) | ≈ 3–8 minutes per clip |
| Still image (Wan single-frame) | ≈ 1 minute once the model is warm |
| Full video | roughly the sum of its parts: 1–3 min per on-camera minute + 3–8 min per b-roll segment + ~1 min per still |
| First job after a restart | + 1–2 minutes (models load lazily on first use) |

Queue a batch and collect results from the "Recent generations" grid — jobs
keep running when you close the browser.

## Requirements

| Component | VRAM (bf16) | Disk |
|---|---|---|
| Fish Audio S2 Pro | ~10 GB | ~10 GB |
| MuseTalk 1.5 (+ whisper-tiny, sd-vae, dwpose) | ~6 GB | ~5 GB |
| Wan2.2 TI2V-5B (diffusers) | ~18 GB (peak ~26 GB) | ~35 GB |

All three fit resident on a 48 GB card; the model manager offloads
least-recently-used pipelines automatically if VRAM runs short (policies per
pipeline via `S2_OFFLOAD` / `MUSETALK_OFFLOAD` / `WAN_OFFLOAD` = `cpu` | `unload`).

> **License note:** S2 Pro weights are under the Fish Audio Research License —
> free for research/non-commercial (hobby) use. Commercial use needs a license
> from Fish Audio.

---

## 1. Local development (no GPU needed for the app itself)

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                                     # 76 tests
python -m uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:3000
```

The UI, API, queue, and validation all work without a GPU; generation jobs fail
with a clear error until the model dependencies and weights exist (that's
expected — GPU work happens on the server).

### Voices

Voices are 10–30 s reference WAV clips in `backend/assets/voices/` listed in
`backend/assets/voices.json` — see `backend/assets/voices/README.md`. Two
synthetic English defaults ship with the repo; replace them with real
recordings for production-quality cloning, and record in the output language
you want (the clone inherits accent and style).

---

## 2. AWS deployment (g6e.2xlarge)

### 2.0 Before you start

- **Request a GPU quota.** New AWS accounts have 0 vCPUs for G-type instances:
  AWS Console → Service Quotas → EC2 → "Running On-Demand G and VT instances" →
  request **8 vCPUs**. Approval takes hours to ~a day, so do this first.
- **Cost:** g6e.2xlarge is ≈ $2.3/hour on demand. **Stop the instance whenever
  you're not generating** — that's the difference between ~$10 and ~$1,600 a
  month. Files, models, and the Elastic IP survive stop/start.
- **Why not the cheaper g6e.xlarge:** its 32 GB of system RAM is not enough —
  Wan2.2 stages ~24 GB of weights through CPU RAM and a 32 GB host swap-freezes
  hard enough to kill SSH (verified the hard way). 64 GB is the floor.
  Multi-GPU instances are pointless for this app — the queue uses one GPU.

### 2.1 Launch the instance

1. EC2 → Launch instance.
2. **AMI — two paths:**
   - *Recommended:* **AWS Deep Learning Base AMI (Ubuntu 22.04)** — NVIDIA
     driver, Docker, and the NVIDIA Container Toolkit are pre-installed; skip
     step 2.2.
   - *Plain:* **Ubuntu Server 22.04 LTS** — install the driver and toolkit
     yourself in step 2.2.
3. Instance type: **g6e.2xlarge**.
4. Storage: **300 GB gp3** root volume (weights ~55 GB + Docker images + outputs).
5. Security group: inbound **22** (your IP only), **80**, **443**. Nothing else.
6. After launch: **Elastic IPs → Allocate → Associate** with the instance, so
   the public IP survives stop/start and your DNS record stays valid.

### 2.2 Driver + Docker (plain Ubuntu path only)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ubuntu-drivers-common
sudo ubuntu-drivers install --gpgpu
sudo reboot
# after reboot:
nvidia-smi                                # must show the L40S

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi   # sanity check
```

### 2.3 Get the code and models

```bash
git clone <your-repo-url> ai-video-studio && cd ai-video-studio
cp .env.example .env                       # defaults are fine to start

# Hugging Face: S2 Pro is license-gated.
python3 -m pip install 'huggingface_hub[cli]'
# 1) create a free account at huggingface.co
# 2) accept the license at https://huggingface.co/fishaudio/s2-pro
# 3) authenticate:
hf auth login

bash backend/scripts/download_models.sh    # ~55 GB, resumable, 30–60 min
```

> **Already downloaded models before this script gained dwpose /
> face-parse-bisent / the top-level sd-vae path?** Move the VAE and re-run the
> script — it skips what's already there and only fetches the two small new
> repos:
>
> ```bash
> mv backend/models/musetalk/sd-vae backend/models/sd-vae 2>/dev/null || true
> bash backend/scripts/download_models.sh
> ```

### 2.4 Start it

```bash
docker compose up -d --build               # first build takes a while (CUDA image + deps)
docker compose logs -f backend             # watch for "gpu worker started"
curl http://localhost:8000/health          # {"status":"ok"}
```

**Validate the pipelines now:** submit one talking-head job and one B-roll job
(via the UI over an SSH tunnel, section 2.7) and watch the logs. The
fish-speech and MuseTalk projects move fast; if an upstream API changed and a
job fails, pin `FISH_SPEECH_REF` / `MUSETALK_REF` in `backend/Dockerfile` to
the last-known-good commits and adjust the two wrapper files
(`backend/app/pipelines/s2_pipeline.py`, `musetalk_pipeline.py`) — all
integration code is contained there by design.

> **Do not bump torch, mmcv, mmpose, or fish-speech independently** — the
> Dockerfile header documents the version matrix. In short: torch 2.4.1 is the
> newest release with prebuilt mmcv wheels (the runtime image has no CUDA
> compiler, so mmcv must never build from source), and fish-speech's
> `torch==2.8.0` pin is relaxed at build time because its inference code
> doesn't actually need 2.8. A build-time import smoke test in the Dockerfile
> catches most incompatibilities before they reach a running job.

### 2.5 Domain + HTTPS + password

1. **DNS:** at your DNS provider (e.g. Vercel DNS), add a plain **A record**:
   `studio` → your Elastic IP. (If your domain lives on Vercel: add it as a DNS
   record, *not* as a domain attached to a Vercel project.)
2. **Nginx:**

```bash
sudo apt install -y nginx apache2-utils
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/ai-video-studio
sudo sed -i 's/studio.example.com/studio.YOURDOMAIN.com/' /etc/nginx/sites-available/ai-video-studio
sudo ln -s /etc/nginx/sites-available/ai-video-studio /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo htpasswd -c /etc/nginx/.htpasswd yourname     # the shared password
sudo nginx -t && sudo systemctl reload nginx
```

3. **HTTPS (Let's Encrypt, auto-renewing):**

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d studio.YOURDOMAIN.com
```

Open `https://studio.YOURDOMAIN.com`, enter the password — done.

### 2.6 Start on reboot

The compose services carry `restart: unless-stopped`, so Docker brings them
back automatically. For explicit control:

```bash
sudo cp deploy/ai-video-studio.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ai-video-studio
```

### 2.7 Premium tier: H100 instance for the 14B models (optional)

The heavy engines (Wan2.2 **A14B** high-quality B-roll; later S2V-14B /
Animate-14B) need ~80 GB VRAM and run on a **separate single-H100 instance**
(AWS P5 family — its quota is separate from G instances and starts at 0;
request "Running On-Demand P instances" ≥ 16 vCPUs). The everyday L40S
instance keeps running the standard tier untouched.

P5 bills ≈ $4+/hour from launch — set up promptly, stop when done.

1. Launch: P5 (single-H100 size), **Deep Learning Base AMI (Ubuntu 22.04)**,
   **400 GB gp3** disk, security group as in 2.1.
2. Set up:

```bash
git clone https://github.com/HrynchukTymofii/avc.git ai-video-studio && cd ai-video-studio
cp .env.example .env
sed -i 's/^PREMIUM_ENABLED=false/PREMIUM_ENABLED=true/' .env
# HF_HUB_DISABLE_XET=1 works around a flaky hf download backend.
# PREMIUM_ENABLED=true makes the script also fetch the ~110 GB A14B weights.
PREMIUM_ENABLED=true HF_HUB_DISABLE_XET=1 bash backend/scripts/download_models.sh
docker compose up -d --build
```

3. Use it via SSH tunnel (`ssh -L 3000:localhost:3000 ubuntu@<ip>`), open
   http://localhost:3000 → B-Roll → model "Wan2.2 A14B — high quality".

> The first A14B run is a **validation run**: the 5B model needed several
> live-GPU fixes on first contact and A14B inherits them, but expect the
> possibility of one or two new one-line issues. Capture logs with the
> command from section 4.

### 2.8 Stop/start workflow (do this — it's the whole cost model)

```bash
aws ec2 stop-instances --instance-ids i-...    # or the console Stop button
aws ec2 start-instances --instance-ids i-...
```

- Stopped instances cost only EBS storage (~$25/month for 300 GB) + the
  Elastic IP (~$3.6/month).
- Everything persists: models, outputs, Docker images, certificates.
- With the Elastic IP attached, the address — and therefore your DNS record —
  never changes.

**SSH tunnel alternative** (no domain/nginx needed, e.g. before DNS is set up):

```bash
ssh -L 3000:localhost:3000 ubuntu@<elastic-ip>
# then open http://localhost:3000
```

---

## 3. API reference

| Endpoint | Description |
|---|---|
| `POST /api/talking-head` | multipart: `avatar` (PNG/JPEG ≤ 20 MB), `script` (≤ 20k chars), `voice` → `{"jobId"}` |
| `POST /api/broll` | multipart: `prompt` (≤ 1k chars), `duration` (3–5), optional `image` → `{"jobId"}` |
| `POST /api/image` | multipart: `prompt` (≤ 1k chars), `orientation` (`landscape`\|`portrait`\|`square`) → `{"jobId"}` |
| `GET /api/status/{jobId}` | `{"status":"queued","position":1}` / `{"status":"processing","progress":62,"stage":"lip-sync"}` / `{"status":"finished","video":...,"audio":...,"image":...}` / `{"status":"failed","error":...}` |
| `GET /api/jobs?kind=&limit=` | recent jobs for the UI grids |
| `GET /api/voices` | configured voice presets |
| `GET /outputs/{jobId}/...` | generated files (static) |

Invalid input returns **422** with a human-readable `detail`.

---

## 4. Troubleshooting

**`could not select device driver "nvidia"` on compose up** — the NVIDIA
Container Toolkit isn't installed/configured (section 2.2), or Docker wasn't
restarted after `nvidia-ctk runtime configure`.

**`CUDA out of memory`** — the manager already offloads idle pipelines and
after any OOM it evicts everything and continues with the next job. If a
specific pipeline keeps OOMing, set its policy to `unload` in `.env` (frees
instead of parking in RAM) and restart. Remember system RAM is 32 GB — don't
set all three to `cpu` on smaller instances.

**Model download fails** — usually the S2 Pro license gate: accept it on the
model page *and* authenticate (`hf auth login` or `HF_TOKEN=...`). Also check
disk: the script needs 70 GB free and prints what it downloaded. Re-running
resumes.

**Job fails instantly with an import/attribute error from fish_speech or
musetalk** — upstream API drift (see 2.4). Pin the refs in
`backend/Dockerfile`, rebuild (`docker compose build backend`), and if needed
adapt the wrapper in `backend/app/pipelines/` — nothing outside those files
touches the model APIs.

**First job after startup is slow** — by design: weights load lazily on first
use (~1–2 min) and stay in memory afterwards. Watch
`docker compose logs -f backend` for `pipeline transition` events.

**"no face detected in the avatar image"** — use a clear, front-facing,
reasonably large portrait; extreme angles and tiny faces fail detection.

**Uploads rejected at 413** — nginx `client_max_body_size` (100 MB in the
example config) or `MAX_UPLOAD_MB` in `.env` (20 MB default).

**Instance IP changed after stop/start** — the Elastic IP wasn't associated
(section 2.1, step 6).

**pip dependency conflicts during image build** — MuseTalk pins older
diffusers/transformers; this image intentionally installs
`requirements-gpu.txt` last so the newer versions win. If MuseTalk breaks
against a newer diffusers at runtime, pin `MUSETALK_REF` to a commit tested
with the versions in `requirements-gpu.txt`.
