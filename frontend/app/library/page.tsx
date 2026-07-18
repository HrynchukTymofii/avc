"use client";

import { useCallback, useEffect, useState } from "react";

import { JobCard } from "@/components/job-card";
import { JobDetailDialog } from "@/components/job-detail-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getJobs } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { JobKind, JobSummary } from "@/types/api";

const FILTERS: { label: string; kind: JobKind | null }[] = [
  { label: "All", kind: null },
  { label: "Full video", kind: "full_video" },
  { label: "Talking head", kind: "talking_head" },
  { label: "B-roll", kind: "broll" },
  { label: "Image", kind: "image" },
  { label: "Upscale", kind: "upscale" },
  { label: "Styles", kind: "lora_training" },
];

export default function LibraryPage() {
  const [filter, setFilter] = useState<JobKind | null>(null);
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await getJobs({ kind: filter ?? undefined, limit: 100 });
      setJobs(response.jobs);
    } catch {
      setJobs([]);
    }
  }, [filter]);

  useEffect(() => {
    setJobs(null);
    void refresh();
  }, [refresh]);

  return (
    <div className="space-y-8">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Library</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Everything you have generated. Click any item to play it, download it,
          regenerate it with the same settings, send it to the upscaler, or
          delete it.
        </p>
      </header>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={() => setFilter(option.kind)}
            className={cn(
              "rounded-lg border px-4 py-1.5 font-mono text-xs uppercase tracking-widest transition-colors",
              filter === option.kind
                ? "border-transparent bg-primary text-primary-foreground"
                : "text-muted-foreground hover:border-foreground/25 hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refresh()}
          className="ml-auto h-8 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
        >
          Refresh
        </Button>
      </div>

      {jobs === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="aspect-video rounded-xl" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-xl border border-dashed p-12 text-center text-sm text-muted-foreground">
          Nothing here yet — generate something and it will show up in your
          library.
        </div>
      ) : (
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}
        >
          {jobs.map((job) => (
            <JobCard
              key={job.jobId}
              job={job}
              onOpen={setOpenJobId}
              onChanged={() => void refresh()}
            />
          ))}
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
