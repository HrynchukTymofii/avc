"use client";

import { PlayIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/format";
import type { JobSummary } from "@/types/api";

interface JobCardProps {
  job: JobSummary;
  /** Stagger index for the fade-up animation. */
  index?: number;
  onOpen: (jobId: string) => void;
}

/** One library tile. The whole card opens the detail dialog — playback,
 * downloads and actions all live there. */
export function JobCard({ job, index = 0, onOpen }: JobCardProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen(job.jobId)}
      className="group/card animate-fade-up overflow-hidden rounded-xl border bg-card text-left transition-colors hover:border-foreground/25"
      style={{ "--delay": `${index * 0.05}s` } as React.CSSProperties}
    >
      {job.status === "finished" && job.video ? (
        <div className="relative">
          <video
            src={job.video}
            preload="metadata"
            muted
            playsInline
            tabIndex={-1}
            className="pointer-events-none aspect-video w-full bg-black"
          />
          <span className="absolute inset-0 flex items-center justify-center">
            <span className="rounded-full bg-black/50 p-3 opacity-0 backdrop-blur-sm transition-opacity group-hover/card:opacity-100">
              <PlayIcon className="size-5 text-white" />
            </span>
          </span>
        </div>
      ) : job.status === "finished" && job.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={job.image}
          alt={job.label || "generated image"}
          className="aspect-video w-full bg-black object-contain"
        />
      ) : job.status === "finished" && job.audio ? (
        <div className="flex aspect-video flex-col items-center justify-center gap-2 bg-black/30 px-4">
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            voice only
          </span>
        </div>
      ) : (
        <div className="flex aspect-video items-center justify-center bg-black/30">
          <JobStatusBadge status={job.status} />
        </div>
      )}
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <p className="truncate text-xs text-muted-foreground" title={job.label}>
          {job.label || "untitled"}
        </p>
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          {timeAgo(job.createdAt)}
        </span>
      </div>
    </button>
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
