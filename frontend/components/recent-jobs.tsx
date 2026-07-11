"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getJobs } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { JobKind, JobSummary } from "@/types/api";

interface RecentJobsProps {
  kind: JobKind;
  /** Bump to refetch (e.g. when the active job reaches a terminal state). */
  refreshKey?: number;
}

export function RecentJobs({ kind, refreshKey = 0 }: RecentJobsProps) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await getJobs({ kind });
      setJobs(response.jobs);
    } catch {
      setJobs([]); // list is a convenience; never let it break the page
    }
  }, [kind]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  if (jobs === null) {
    return (
      <section className="space-y-3">
        <RecentHeader onRefresh={refresh} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="aspect-video rounded-lg" />
          ))}
        </div>
      </section>
    );
  }

  if (jobs.length === 0) return null;

  return (
    <section className="space-y-3">
      <RecentHeader onRefresh={refresh} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {jobs.map((job, index) => (
          <article
            key={job.jobId}
            className="animate-fade-up overflow-hidden rounded-lg border bg-card"
            style={{ "--delay": `${index * 0.05}s` } as React.CSSProperties}
          >
            {job.status === "finished" && job.video ? (
              <video
                src={job.video}
                controls
                preload="metadata"
                playsInline
                className="aspect-video w-full bg-black"
              />
            ) : job.status === "finished" && job.image ? (
              <a href={job.image} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={job.image}
                  alt={job.label || "generated image"}
                  className="aspect-video w-full bg-black object-contain"
                />
              </a>
            ) : job.status === "finished" && job.audio ? (
              <div className="flex aspect-video flex-col items-center justify-center gap-3 bg-black/30 px-4">
                <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                  voice only
                </span>
                <audio src={job.audio} controls className="w-full" />
              </div>
            ) : (
              <div className="flex aspect-video items-center justify-center bg-black/30">
                <StatusBadge status={job.status} />
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
          </article>
        ))}
      </div>
    </section>
  );
}

function RecentHeader({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Recent generations
      </h2>
      <Button
        variant="ghost"
        size="sm"
        onClick={onRefresh}
        className="h-6 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
      >
        Refresh
      </Button>
    </div>
  );
}

function StatusBadge({ status }: { status: JobSummary["status"] }) {
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
