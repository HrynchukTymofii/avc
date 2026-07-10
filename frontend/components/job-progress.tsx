"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import type { JobStatus } from "@/types/api";
import { stageLabel } from "@/types/api";

/** Console-style readout for a job in flight. Renders nothing when there is no
 * job or the job finished (the parent shows the result instead). */
export function JobProgress({ status }: { status: JobStatus | null }) {
  if (!status) return null;

  if (status.status === "queued") {
    return (
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center gap-3">
          <span className="rec-dot rec-dot-live" aria-hidden />
          <span className="font-mono text-xs uppercase tracking-widest">
            Queued &middot; position #{status.position}
          </span>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          One GPU, one job at a time — this job starts when the queue ahead of it clears.
          You can close this page; the job keeps running.
        </p>
      </div>
    );
  }

  if (status.status === "processing") {
    return (
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="rec-dot rec-dot-live" aria-hidden />
            <span className="font-mono text-xs uppercase tracking-widest">
              {stageLabel(status.stage)}
            </span>
          </div>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {status.progress}%
          </span>
        </div>
        <Progress value={status.progress} className="mt-3 h-1.5" />
      </div>
    );
  }

  if (status.status === "failed") {
    return (
      <Alert variant="destructive">
        <AlertTitle className="font-mono text-xs uppercase tracking-widest">
          Generation failed
        </AlertTitle>
        <AlertDescription>{status.error}</AlertDescription>
      </Alert>
    );
  }

  return null;
}
