"use client";

import {
  DownloadIcon,
  RefreshCwIcon,
  Trash2Icon,
  Wand2Icon,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { deleteJob, regenerateJob, submitUpscale } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { JobSummary } from "@/types/api";

interface JobCardProps {
  job: JobSummary;
  onOpen: (jobId: string) => void;
  /** Called after a quick action changed the library (regenerate/upscale/delete). */
  onChanged?: () => void;
}

/** Uniform grid tile. Click opens the detail dialog; hovering reveals square
 * quick-action buttons (download / upscale / regenerate / delete) on the media
 * itself, so common actions never need the dialog. */
export function JobCard({ job, onOpen, onChanged }: JobCardProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const downloadUrl = job.video ?? job.image ?? job.audio;
  const canUpscale =
    job.status === "finished" && (job.video || job.image) && job.kind !== "upscale";

  const run = async (action: string, work: () => Promise<void>) => {
    setBusy(action);
    setError(null);
    try {
      await work();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(job.jobId)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen(job.jobId);
      }}
      className="group/card cursor-pointer overflow-hidden rounded-lg border bg-card text-left transition-colors hover:border-foreground/30"
    >
      <div className="relative">
        {job.status === "finished" && job.video ? (
          <video
            src={job.video}
            preload="metadata"
            muted
            playsInline
            tabIndex={-1}
            className="pointer-events-none aspect-video w-full bg-black object-cover"
          />
        ) : job.status === "finished" && job.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={job.image}
            alt={job.label || "generated image"}
            className="aspect-video w-full bg-black object-cover"
          />
        ) : job.status === "finished" && job.audio ? (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 bg-black/40 px-4">
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              voice over
            </span>
            <audio
              src={job.audio}
              controls
              className="w-full max-w-64"
              onClick={(event) => event.stopPropagation()}
            />
          </div>
        ) : (
          <div className="flex aspect-video w-full items-center justify-center bg-black/40">
            <JobStatusBadge status={job.status} />
          </div>
        )}

        {/* hover quick actions */}
        <div
          className="absolute bottom-2 right-2 flex gap-1.5 opacity-0 transition-opacity group-hover/card:opacity-100 group-focus-within/card:opacity-100"
          onClick={(event) => event.stopPropagation()}
        >
          {downloadUrl && (
            <a
              href={downloadUrl}
              download
              title="Download"
              className="flex size-8 items-center justify-center rounded-lg bg-black/70 text-white backdrop-blur-sm transition-colors hover:bg-black/90"
            >
              <DownloadIcon className="size-4" />
            </a>
          )}
          {canUpscale && (
            <button
              type="button"
              title="Upscale with Real-ESRGAN"
              disabled={busy !== null}
              onClick={() =>
                run("upscale", async () => {
                  await submitUpscale({ sourceJob: job.jobId });
                })
              }
              className="flex size-8 items-center justify-center rounded-lg bg-black/70 text-white backdrop-blur-sm transition-colors hover:bg-black/90 disabled:opacity-50"
            >
              <Wand2Icon className={cn("size-4", busy === "upscale" && "animate-pulse")} />
            </button>
          )}
          <button
            type="button"
            title="Regenerate with the same settings"
            disabled={busy !== null}
            onClick={() =>
              run("regenerate", async () => {
                await regenerateJob(job.jobId);
              })
            }
            className="flex size-8 items-center justify-center rounded-lg bg-black/70 text-white backdrop-blur-sm transition-colors hover:bg-black/90 disabled:opacity-50"
          >
            <RefreshCwIcon className={cn("size-4", busy === "regenerate" && "animate-spin")} />
          </button>
          <button
            type="button"
            title={confirmDelete ? "Click again to delete" : "Delete"}
            disabled={busy !== null}
            onClick={() => {
              if (!confirmDelete) {
                setConfirmDelete(true);
                setTimeout(() => setConfirmDelete(false), 2500);
                return;
              }
              void run("delete", async () => {
                await deleteJob(job.jobId);
              });
            }}
            className={cn(
              "flex size-8 items-center justify-center rounded-lg backdrop-blur-sm transition-colors disabled:opacity-50",
              confirmDelete
                ? "bg-destructive text-white"
                : "bg-black/70 text-white hover:bg-black/90",
            )}
          >
            <Trash2Icon className={cn("size-4", busy === "delete" && "animate-pulse")} />
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 px-3 py-2">
        {error ? (
          <p className="truncate text-xs text-destructive" title={error}>
            {error}
          </p>
        ) : (
          <p className="truncate text-xs text-muted-foreground" title={job.label}>
            {job.label || "untitled"}
          </p>
        )}
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          {timeAgo(job.createdAt)}
        </span>
      </div>
    </div>
  );
}

export function JobStatusBadge({ status }: { status: JobSummary["status"] }) {
  if (status === "failed") {
    return <Badge variant="destructive">failed</Badge>;
  }
  return (
    <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
      <span className="rec-dot rec-dot-live" aria-hidden />
      {status}
    </span>
  );
}
