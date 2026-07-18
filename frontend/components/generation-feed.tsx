"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { JobCard, jobTiles } from "@/components/job-card";
import { JobDetailDialog } from "@/components/job-detail-dialog";
import { getJobs } from "@/lib/api";
import { stageLabel } from "@/types/api";
import type { JobKind, JobStatus, JobSummary } from "@/types/api";

interface GenerationFeedProps {
  kind: JobKind;
  /** Bump to refetch (on submit and when the active job finishes). */
  refreshKey?: number;
  /** Active job status — rendered as a live tile at the end of the grid. */
  status?: JobStatus | null;
  /** The job behind `status` — its list card is hidden while the live tile
   * shows, so a freshly submitted job doesn't appear twice. */
  activeJobId?: string | null;
  /** Narrow the list further (e.g. voice-only talking-head jobs). */
  filterJobs?: (job: JobSummary) => boolean;
  emptyTitle: string;
  emptyHint: string;
}

/** History as an adaptive grid, oldest first — the newest tiles sit at the
 * bottom, right above the composer. Tiles carry hover quick actions and open
 * the detail dialog on click. */
export function GenerationFeed({
  kind,
  refreshKey = 0,
  status = null,
  activeJobId = null,
  filterJobs,
  emptyTitle,
  emptyHint,
}: GenerationFeedProps) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  // Follow the newest generation until the user scrolls up to browse history;
  // media loading in tiles above re-anchors while following.
  const followBottom = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const response = await getJobs({ kind, limit: 60 });
      const list = [...response.jobs].reverse(); // oldest first
      setJobs(filterJobs ? list.filter(filterJobs) : list);
    } catch {
      setJobs([]);
    }
  }, [kind, filterJobs]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  // Several generations can sit in the queue at once but only the newest one
  // gets the live status tile — keep refetching while any listed job is still
  // working so the older tiles move queued → processing → finished on their own.
  useEffect(() => {
    const working = jobs?.some(
      (job) => job.status === "queued" || job.status === "processing",
    );
    if (!working) return;
    const timer = setTimeout(() => void refresh(), 4000);
    return () => clearTimeout(timer);
  }, [jobs, refresh]);

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
    // in flow, so max scroll puts the newest tiles right above it
    if (followBottom.current) {
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }
  }, []);

  const jobCount = jobs?.length ?? 0;
  useEffect(() => {
    followBottom.current = true; // a refresh (new submit / job change) re-follows
    anchor();
  }, [jobCount, refreshKey, status?.status, anchor]);

  const showActiveTile =
    status !== null && (status.status === "queued" || status.status === "processing");
  // the live tile already represents the active job — hide its list card
  const visibleJobs =
    showActiveTile && activeJobId
      ? (jobs?.filter((job) => job.jobId !== activeJobId) ?? null)
      : jobs;

  if (jobs !== null && jobs.length === 0 && !showActiveTile) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-center">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">{emptyTitle}</h1>
        <p className="max-w-md text-sm text-muted-foreground">{emptyHint}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-end py-6">
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}
        // media sizes settle after first paint — keep the view anchored
        onLoadCapture={anchor}
      >
        {visibleJobs?.flatMap((job) =>
          jobTiles(job).map((tile) => (
            <JobCard
              key={tile.key}
              job={job}
              image={tile.image}
              imageKey={tile.imageKey}
              onOpen={setOpenJobId}
              onChanged={() => void refresh()}
            />
          )),
        )}
        {showActiveTile && <ActiveJobTile status={status} />}
      </div>
      <JobDetailDialog
        jobId={openJobId}
        onClose={() => setOpenJobId(null)}
        onChanged={() => void refresh()}
      />
    </div>
  );
}

/** The in-progress generation as a normal grid tile: spinner + percent. */
function ActiveJobTile({ status }: { status: JobStatus }) {
  return (
    <div className="overflow-hidden rounded-lg border border-primary/40 bg-card">
      <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 bg-black/40">
        <span className="size-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
        {status.status === "processing" ? (
          <span className="font-mono text-sm tabular-nums text-foreground/90">
            {status.progress}%
          </span>
        ) : (
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            queued #{status.status === "queued" ? status.position : 1}
          </span>
        )}
      </div>
      <div className="px-3 py-2">
        <p className="truncate font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {status.status === "processing" ? stageLabel(status.stage) : "waiting for the GPU"}
        </p>
      </div>
    </div>
  );
}
