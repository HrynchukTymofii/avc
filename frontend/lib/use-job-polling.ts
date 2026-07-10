"use client";

/** Polls /api/status/{jobId} every 2 seconds until the job reaches a terminal
 * state. Returns null while no job is being tracked. */

import { useEffect, useState } from "react";

import { getStatus } from "@/lib/api";
import type { JobStatus } from "@/types/api";

export function isTerminal(status: JobStatus | null): boolean {
  return status?.status === "finished" || status?.status === "failed";
}

export function useJobPolling(jobId: string | null, intervalMs = 2000): JobStatus | null {
  const [status, setStatus] = useState<JobStatus | null>(null);

  useEffect(() => {
    if (!jobId) {
      setStatus(null);
      return;
    }
    setStatus(null);
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      let next: JobStatus;
      try {
        next = await getStatus(jobId);
      } catch (error) {
        // Transient network/proxy hiccups shouldn't kill an in-flight job view;
        // keep polling — only a real backend "failed" status is terminal.
        if (!cancelled) timer = setTimeout(tick, intervalMs);
        return;
      }
      if (cancelled) return;
      setStatus(next);
      if (next.status === "queued" || next.status === "processing") {
        timer = setTimeout(tick, intervalMs);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return status;
}
