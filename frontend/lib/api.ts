/** Typed fetch client for the backend API.
 *
 * Requests go to the same origin; next.config.ts rewrites /api and /outputs to
 * the backend (nginx does the same in production), so no CORS is involved.
 */

import type {
  JobCreatedResponse,
  JobKind,
  JobListResponse,
  JobStatus,
  LorasResponse,
  ModelsResponse,
  VoicesResponse,
} from "@/types/api";

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiRequestError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export async function getModels(): Promise<ModelsResponse> {
  return handle(await fetch("/api/models"));
}

export async function submitTalkingHead(input: {
  avatar: File | null;
  script: string;
  voice: string;
  voiceOnly?: boolean;
  model?: string;
}): Promise<JobCreatedResponse> {
  const form = new FormData();
  if (input.avatar) form.append("avatar", input.avatar);
  form.append("script", input.script);
  form.append("voice", input.voice);
  if (input.voiceOnly) form.append("voice_only", "true");
  if (input.model) form.append("model", input.model);
  return handle(await fetch("/api/talking-head", { method: "POST", body: form }));
}

export async function submitBroll(input: {
  prompt: string;
  duration: number;
  image?: File | null;
  model?: string;
  lora?: string;
}): Promise<JobCreatedResponse> {
  const form = new FormData();
  form.append("prompt", input.prompt);
  form.append("duration", String(input.duration));
  if (input.image) form.append("image", input.image);
  if (input.model) form.append("model", input.model);
  if (input.lora) form.append("lora", input.lora);
  return handle(await fetch("/api/broll", { method: "POST", body: form }));
}

export async function submitImage(input: {
  prompt: string;
  orientation: string;
  model?: string;
  count?: number;
  lora?: string;
}): Promise<JobCreatedResponse> {
  const form = new FormData();
  form.append("prompt", input.prompt);
  form.append("orientation", input.orientation);
  if (input.model) form.append("model", input.model);
  if (input.count && input.count > 1) form.append("count", String(input.count));
  if (input.lora) form.append("lora", input.lora);
  return handle(await fetch("/api/image", { method: "POST", body: form }));
}

export async function submitLoraTraining(input: {
  name: string;
  trigger: string;
  images: File[];
  description?: string;
  steps?: number;
}): Promise<JobCreatedResponse> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("trigger", input.trigger);
  for (const image of input.images) form.append("images", image);
  if (input.description) form.append("description", input.description);
  if (input.steps) form.append("steps", String(input.steps));
  return handle(await fetch("/api/lora-training", { method: "POST", body: form }));
}

export async function getLoras(): Promise<LorasResponse> {
  return handle(await fetch("/api/loras"));
}

export async function deleteLora(id: string): Promise<void> {
  const response = await fetch(`/api/loras/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new ApiRequestError(`Delete failed (${response.status})`, response.status);
  }
}

export async function submitFullVideo(input: {
  script: string;
  voice: string;
  avatar: File | null;
  orientation?: string;
  clips?: File[];
  model?: string;
}): Promise<JobCreatedResponse> {
  const form = new FormData();
  form.append("script", input.script);
  form.append("voice", input.voice);
  if (input.avatar) form.append("avatar", input.avatar);
  if (input.orientation) form.append("orientation", input.orientation);
  for (const clip of input.clips ?? []) form.append("clips", clip);
  if (input.model) form.append("model", input.model);
  return handle(await fetch("/api/full-video", { method: "POST", body: form }));
}

export async function getStatus(jobId: string): Promise<JobStatus> {
  return handle(await fetch(`/api/status/${encodeURIComponent(jobId)}`));
}

export async function getJobs(options?: {
  kind?: JobKind;
  limit?: number;
}): Promise<JobListResponse> {
  const params = new URLSearchParams();
  if (options?.kind) params.set("kind", options.kind);
  if (options?.limit) params.set("limit", String(options.limit));
  const query = params.size > 0 ? `?${params}` : "";
  return handle(await fetch(`/api/jobs${query}`));
}

export async function getVoices(): Promise<VoicesResponse> {
  return handle(await fetch("/api/voices"));
}
