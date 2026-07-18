/** TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas.py). */

export type JobKind =
  | "talking_head"
  | "broll"
  | "image"
  | "full_video"
  | "lora_training"
  | "upscale";

export interface JobCreatedResponse {
  jobId: string;
}

export type Stage =
  | "tts"
  | "motion"
  | "lip-sync"
  | "encoding"
  | "diffusion"
  | "starting"
  | "preparing dataset"
  | "freeing gpu"
  | "training"
  | "saving style"
  | "extracting frames"
  | "upscaling";

export const STAGE_LABELS: Record<Stage, string> = {
  starting: "Starting",
  tts: "Generating speech",
  motion: "Generating head motion",
  "lip-sync": "Animating avatar",
  diffusion: "Generating", // shared by video and image jobs
  encoding: "Encoding video",
  "preparing dataset": "Preparing dataset",
  "freeing gpu": "Freeing the GPU",
  training: "Training style",
  "saving style": "Saving style",
  "extracting frames": "Extracting frames",
  upscaling: "Upscaling",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as Stage] ?? stage;
}

/** Discriminated on `status` — switch statements narrow exhaustively. */
export type JobStatus =
  | { status: "queued"; position: number }
  | { status: "processing"; progress: number; stage: string; audio?: string }
  | {
      status: "finished";
      video?: string;
      audio?: string;
      image?: string;
      images?: string[];
      /** Trained style id (lora-training jobs only). */
      lora?: string;
    }
  | { status: "failed"; error: string };

export interface JobSummary {
  jobId: string;
  kind: JobKind;
  status: "queued" | "processing" | "finished" | "failed";
  label: string;
  createdAt: string; // ISO 8601
  video?: string;
  audio?: string;
  image?: string;
  /** All generated images for multi-image jobs (image holds the first one). */
  images?: string[];
  /** talking_head only: true = narration-only job (Voice Over tab). */
  voiceOnly?: boolean;
}

export interface JobListResponse {
  jobs: JobSummary[];
}

export interface JobDetail {
  jobId: string;
  kind: JobKind;
  status: "queued" | "processing" | "finished" | "failed";
  label: string;
  createdAt: string; // ISO 8601
  cost: number;
  /** Engine id / prompt / voice the job was created with (absent on old history). */
  model?: string;
  prompt?: string;
  voice?: string;
  error?: string;
  video?: string;
  audio?: string;
  image?: string;
  images?: string[];
  canRegenerate: boolean;
  canUpscale: boolean;
}

export interface EngineInfo {
  id: string;
  label: string;
  tier: "standard" | "premium";
  credits: string;
  available: boolean;
  default: boolean;
}

export interface ModelsResponse {
  models: Record<string, EngineInfo[]>;
}

export interface LoraStyle {
  id: string;
  name: string;
  trigger: string;
  base: string;
  createdAt: string; // ISO 8601
}

export interface LorasResponse {
  loras: LoraStyle[];
}

export interface Voice {
  id: string;
  name: string;
  language: string;
}

export interface VoicesResponse {
  voices: Voice[];
}

export interface CreditsResponse {
  allowance: number;
  spent: number;
  balance: number;
  unlimited: boolean;
}

export interface ApiError {
  detail: string;
}
