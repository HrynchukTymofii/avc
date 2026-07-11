/** TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas.py). */

export type JobKind = "talking_head" | "broll" | "image";

export interface JobCreatedResponse {
  jobId: string;
}

export type Stage = "tts" | "motion" | "lip-sync" | "encoding" | "diffusion" | "starting";

export const STAGE_LABELS: Record<Stage, string> = {
  starting: "Starting",
  tts: "Generating speech",
  motion: "Generating head motion",
  "lip-sync": "Animating avatar",
  diffusion: "Generating", // shared by video and image jobs
  encoding: "Encoding video",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as Stage] ?? stage;
}

/** Discriminated on `status` — switch statements narrow exhaustively. */
export type JobStatus =
  | { status: "queued"; position: number }
  | { status: "processing"; progress: number; stage: string; audio?: string }
  | { status: "finished"; video?: string; audio?: string; image?: string }
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
