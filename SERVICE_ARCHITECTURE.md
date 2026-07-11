# AI Video Studio — Service Architecture

How the single-user MVP grows into a paid multi-user service: model catalog &
selection, credits, authentication, payments, and the scaling path at 10 → 100
→ 1000 users. The MVP blueprint stays in `ARCHITECTURE.md`; this file is the
forward plan.

---

## 1. Where we are (baseline)

One g6e.2xlarge (L40S 44 GB usable, 64 GB RAM) runs everything: FastAPI backend
with a **single sequential GPU queue**, three model families (S2 Pro voice,
MuseTalk lip-sync, Wan2.2-5B video/image), Next.js frontend, nginx + basic auth
+ HTTPS at `studio.fibipals.com`, outputs on local EBS, jobs as `status.json`
files. Cost model: stop the instance when idle.

Everything below is staged so that **each step keeps the previous one working**.

---

## 2. Model catalog and tiers

Two hardware tiers, decided 2026-07-11:

- **Standard tier — L40S (current instance).** Everything built today.
- **Premium tier — H100 80 GB.** The 14B/A14B models; AWS P5 (quota pending)
  or per-hour rentals (RunPod/Lambda) until then.

| Category | Model | Tier | Status | Indicative credits* |
|---|---|---|---|---|
| Voice over | Fish S2 Pro (clone from reference) | Standard | live | 1 /min of audio |
| Talking head | MuseTalk (still photo, lips only) | Standard | live | 2 /min |
| Talking head | Hybrid animate (Wan idle clip + MuseTalk) | Standard | live | 4 /min + 10 flat |
| Talking head | **Wan2.2-S2V-14B** (full speech-driven motion) | Premium | planned | 40 /min |
| Character video | **Wan2.2-Animate-14B** (driving-video reenactment) | Premium | planned | 40 /min |
| B-roll video | Wan2.2 TI2V-5B (T2V + I2V) | Standard | live | 8 /5 s clip |
| B-roll video | **Wan2.2 T2V/I2V-A14B** (high quality) | Premium | planned | 30 /5 s clip |
| Image | Wan 5B single-frame | Standard | live | 1 /image |
| Image | **FLUX.1** | Standard (fits L40S) | planned | 2 /image |

*Credits ≈ proportional to GPU-seconds; calibrate after measuring. Rule of
thumb: 1 credit ≈ 10 GPU-seconds on the L40S; premium models priced at H100
cost (~2× the $/hour of the L40S).

**Licensing gate before charging money:** S2 Pro (research license — needs a
commercial license or replacement, e.g. XTTS/Fish commercial plan), FLUX.1-dev
(non-commercial — use FLUX.1-schnell Apache or license dev), MuseTalk (verify).
Wan 2.2 family is Apache 2.0 — safe.

### Model selection plumbing (build first, no new GPUs needed)

- **Backend model registry:** each job kind exposes a list of engines —
  `{id, label, tier, credit_rate, available}` — served by `GET /api/models`.
  `available` is computed from env (`PREMIUM_TIER_URL` unset ⇒ premium models
  listed but disabled). Generation endpoints take a `model` field; the
  processor dispatches to the right pipeline.
- **Frontend:** nav bar becomes three groups — **Voice Over · Video · Image**
  — with hover dropdowns listing the modes/models inside each (lip-sync,
  animated head, B-roll, character video…). Premium entries render with a
  "requires premium GPU" badge until available.
- Premium pipelines are scaffolded behind the registry so wiring exists before
  the H100 does; they are integration-tested the day the GPU arrives (every
  model so far needed live-GPU debugging — expect the same, do not mark
  premium models "done" until they have produced output on real hardware).

---

## 3. Authentication (phases)

**Phase 0 (now):** nginx basic auth — one shared password. Fine while all
users are trusted friends.

**Phase 1 — accounts (needed the moment credits exist):**
- **Managed auth, don't build it:** Clerk or Auth0 (fastest, generous free
  tiers) or AWS Cognito (cheapest at scale, clunkier DX). Next.js gets the
  hosted login; the backend verifies the JWT on every `/api/*` request via
  middleware (JWKS check, ~20 lines of FastAPI).
- `users` table keyed by the auth provider's `sub`. Jobs gain `user_id`;
  `/api/jobs` and `/outputs/*` become owner-scoped (signed URLs or a
  permission check in the outputs route — **stop serving outputs as public
  static files** at this point).
- Keep basic auth on a separate `admin.` host for yourself.

**Phase 2:** org/team accounts, API keys for programmatic access. Only if
customers ask.

---

## 4. Credits and payments

**Ledger, not a balance column.** One append-only `credit_transactions` table:
`(id, user_id, delta, reason, job_id?, stripe_ref?, created_at)`; balance =
`SUM(delta)`. This makes refunds, disputes, and debugging trivial.

Flow per job:
1. **Submit:** compute estimated cost from the registry → reject if balance
   is insufficient → write `delta = -estimate` (hold) → enqueue.
2. **Finish:** if actual cost differs meaningfully (audio length!), write an
   adjustment row.
3. **Fail:** write `delta = +estimate` (automatic refund). Failures are the
   service's problem, not the user's.

**Payments — Stripe Checkout, nothing custom:**
- Sell credit packs (e.g. 100 / 500 / 2000) as one-time Checkout sessions;
  a webhook (`checkout.session.completed`) writes the credit-grant row.
  Idempotency: store the Stripe event id, ignore duplicates.
- Subscriptions (monthly credit allowance) later — same webhook pattern.
- Never store card data; Stripe hosts the payment page. VAT/OSS handled by
  Stripe Tax when EU customers appear.

**Free tier:** sign-up grant (e.g. 20 credits) so people can try one of
everything. Rate-limit free accounts (N jobs/day) to protect the queue.

---

## 5. Data layer evolution

| Stage | Jobs/state | Files |
|---|---|---|
| Now | `status.json` per job | local EBS, served by the backend |
| With accounts | **Postgres** (users, jobs, credit ledger) — managed RDS or Neon/Supabase | **S3** for outputs + presigned URLs; CloudFront in front when traffic grows |

Move to Postgres/S3 in the same release as auth — both exist to answer "whose
job/file is this?". The queue itself can stay in-process until stage B below.

---

## 6. Scaling stages

### Stage A — ~10 users (friends & first testers)
Current single instance survives this **unchanged** apart from auth+credits.
- The sequential queue is the feature, not the bug: jobs just wait. Show queue
  position honestly (already built).
- Instance now runs on a schedule instead of manual stop/start: auto-stop
  after N idle minutes (small cron + CloudWatch alarm), auto-start on first
  job submission (a tiny always-on t4g.nano running just nginx + the API can
  wake the GPU box, or accept "first job of the day is slow").
- **Bottleneck to watch:** one 20-min voiceover job blocks everyone for ~40
  min. Add per-user concurrent-job limits (1) and a max-length cap for
  non-premium users.

### Stage B — ~100 users
The API and the GPU must separate.
- **Control plane (always on, cheap):** API + frontend + Postgres + Redis on
  a small non-GPU instance (or ECS/Fly). Owns auth, credits, job records.
- **Work plane (elastic):** GPU workers pull jobs from a queue (**SQS** or
  Redis streams — SQS is less to operate). Each worker = today's backend
  minus the HTTP layer: model manager + processors + an SQS poll loop.
  Progress/results written back via Postgres + S3.
- **Fleet shape:** 2–4 × L40S (g6e) in an auto-scaling group scaled on queue
  depth (scale to zero overnight), + 1 H100 node (or RunPod burst) consuming
  only the premium queue.
- **Pin model families to worker pools** (voice+lip-sync pool vs video pool)
  once there are ≥2 workers — avoids the load/offload thrash that dominated
  today's debugging, and keeps models hot.
- Separate queues per tier so a premium job never waits behind 30 B-roll jobs.

### Stage C — ~1000 users
Same shapes, bigger numbers, plus operational maturity:
- **Priority + fairness:** weighted queues (paid > free), per-user in-flight
  caps, job preemption for >10-min jobs (chunk long voiceovers — S2 already
  splits scripts; persist per-chunk progress so retries don't restart).
- **Capacity mix:** baseline reserved/savings-plan GPUs + spot for burst
  (jobs are retryable by design — spot interruption = requeue) + serverless
  GPU (Modal/RunPod) as overflow so the queue never exceeds an SLA.
- **Observability:** queue depth, GPU-seconds per model, cost per job,
  failure rate per model — Grafana + Prometheus (or CloudWatch). Alert on
  queue latency, not CPU.
- **Throughput math to size the fleet:** one L40S ≈ 6–8 B-roll clips/hour or
  ~15–20 min of talking-head/hour. 1000 users × 2 jobs/day ≈ 2000 jobs/day ≈
  steady 10–15 L40S-equivalents at peak — this is where per-model queues and
  spot pricing decide the margin.
- Multi-region only when latency-sensitive customers or data-residency
  demand it; GPU capacity, not latency, is the real constraint.

### Parallelism notes (all stages)
- **One job per GPU at a time** stays the rule — video diffusion saturates the
  card; "parallel on one GPU" only slows both jobs and risks OOM.
- Concurrency = more workers, never threads on one card.
- The only safe intra-job parallelism: pipeline stages of *different* jobs on
  *different* pools (user A's TTS on the voice pool while user B's Wan runs
  on the video pool) — this falls out of pinned pools for free.

---

## 7. Build order (each step ships alone)

1. **Model registry + `model` param + nav dropdowns + credit *costs* in the
   registry** (no accounts yet — costs are displayed, not charged).
2. **FLUX image pipeline** (runs on the L40S today; schnell variant for
   license safety).
3. **Auth (Clerk/Cognito) + Postgres + S3 + owner-scoped jobs.**
4. **Credit ledger + Stripe checkout + free-tier grant.**
5. **Premium scaffolds live** the week the H100 exists: S2V-14B, Animate-14B,
   A14B — integrated and debugged on the real card, then flipped `available`.
6. **Control/work plane split** when concurrent users hurt (Stage B).

License review (S2 Pro replacement or commercial license) must land before
step 4 charges anyone real money.
