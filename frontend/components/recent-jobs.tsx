"use client";

import { useCallback, useEffect, useState } from "react";

import { JobCard, jobTiles } from "@/components/job-card";
import { JobDetailDialog } from "@/components/job-detail-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getJobs } from "@/lib/api";
import type { JobKind, JobSummary } from "@/types/api";

interface RecentJobsProps {
  kind: JobKind;
  /** Bump to refetch (e.g. when the active job reaches a terminal state). */
  refreshKey?: number;
}

export function RecentJobs({ kind, refreshKey = 0 }: RecentJobsProps) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [openJobId, setOpenJobId] = useState<string | null>(null);

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
            <Skeleton key={i} className="aspect-video rounded-xl" />
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
        {jobs.flatMap((job) =>
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
      </div>
      <JobDetailDialog
        jobId={openJobId}
        onClose={() => setOpenJobId(null)}
        onChanged={() => void refresh()}
      />
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
