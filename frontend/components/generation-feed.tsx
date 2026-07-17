"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { JobDetailDialog } from "@/components/job-detail-dialog";
import { JobProgress } from "@/components/job-progress";
import { JobStatusBadge } from "@/components/job-card";
import { getJobs } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { JobKind, JobStatus, JobSummary } from "@/types/api";

interface GenerationFeedProps {
  kind: JobKind;
  /** Bump to refetch (on submit and when the active job finishes). */
  refreshKey?: number;
  /** Active job status — rendered as a live progress bubble at the bottom. */
  status?: JobStatus | null;
  emptyTitle: string;
  emptyHint: string;
}

/** Chat-style history: oldest at the top, newest directly above the composer.
 * Every card opens the detail dialog (download / regenerate / upscale / delete). */
export function GenerationFeed({
  kind,
  refreshKey = 0,
  status = null,
  emptyTitle,
  emptyHint,
}: GenerationFeedProps) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  // Follow the newest generation (chat behavior) until the user scrolls up to
  // browse history; media loading in above cards re-anchors while following.
  const followBottom = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const response = await getJobs({ kind, limit: 30 });
      setJobs([...response.jobs].reverse()); // oldest first, newest at the bottom
    } catch {
      setJobs([]);
    }
  }, [kind]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  useEffect(() => {
    const onScroll = () => {
      const distance =
        document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
      followBottom.current = distance < 160;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const anchor = useCallback(() => {
    // scroll the document fully down — the sticky composer sits after the feed
    // in flow, so max scroll puts the newest card right above it
    if (followBottom.current) {
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }
  }, []);

  const jobCount = jobs?.length ?? 0;
  useEffect(() => {
    followBottom.current = true; // a refresh (new submit / job change) re-follows
    anchor();
  }, [jobCount, refreshKey, status?.status, anchor]);

  if (jobs !== null && jobs.length === 0 && !status) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-center">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">{emptyTitle}</h1>
        <p className="max-w-md text-sm text-muted-foreground">{emptyHint}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-end gap-4 py-6">
      {jobs?.map((job) => (
        <FeedCard key={job.jobId} job={job} onOpen={setOpenJobId} onMediaLoad={anchor} />
      ))}
      {status && status.status !== "finished" && (
        <div className="max-w-xl">
          <JobProgress status={status} />
        </div>
      )}
      <JobDetailDialog
        jobId={openJobId}
        onClose={() => setOpenJobId(null)}
        onChanged={() => void refresh()}
      />
    </div>
  );
}

function FeedCard({
  job,
  onOpen,
  onMediaLoad,
}: {
  job: JobSummary;
  onOpen: (jobId: string) => void;
  /** Media sizes arrive after render — lets the feed re-anchor to the bottom. */
  onMediaLoad: () => void;
}) {
  return (
    // div, not <button>: audio players render inside and nested interactive
    // elements are invalid HTML
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(job.jobId)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen(job.jobId);
      }}
      className="group/card w-fit max-w-full cursor-pointer overflow-hidden rounded-2xl border bg-card text-left transition-colors hover:border-foreground/30"
    >
      {job.status === "finished" && job.video ? (
        <video
          src={job.video}
          preload="metadata"
          muted
          playsInline
          tabIndex={-1}
          onLoadedMetadata={onMediaLoad}
          className="pointer-events-none max-h-96 w-auto max-w-full bg-black"
        />
      ) : job.status === "finished" && job.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={job.image}
          alt={job.label || "generated image"}
          onLoad={onMediaLoad}
          className="max-h-96 w-auto max-w-full bg-black"
        />
      ) : job.status === "finished" && job.audio ? (
        <div className="flex min-w-72 items-center gap-3 px-4 pt-4">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            audio
          </span>
          <audio
            src={job.audio}
            controls
            className="w-full"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      ) : (
        <div className="flex min-w-72 items-center px-4 pt-4">
          <JobStatusBadge status={job.status} />
        </div>
      )}
      <div className="flex items-center justify-between gap-6 px-4 py-2.5">
        <p className="truncate text-xs text-muted-foreground" title={job.label}>
          {job.label || "untitled"}
        </p>
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          {timeAgo(job.createdAt)}
        </span>
      </div>
    </div>
  );
}
