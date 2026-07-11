"use client";

import { useEffect, useRef, useState } from "react";

import { FileDropzone } from "@/components/file-dropzone";
import { JobProgress } from "@/components/job-progress";
import { ModelSelect } from "@/components/model-select";
import { RecentJobs } from "@/components/recent-jobs";
import { VideoPreview } from "@/components/video-preview";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { submitBroll } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const DURATIONS = [3, 4, 5] as const;

export default function BrollPage() {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState<string>("5");
  const [image, setImage] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  const busy = submitting || (jobId !== null && !isTerminal(status));

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const handleSubmit = async () => {
    if (!prompt.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitBroll({
        prompt,
        duration: Number(duration),
        image,
        model: model || undefined,
      });
      setJobId(response.jobId);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setJobId(null);
    setPrompt("");
    setImage(null);
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">B-Roll Generator</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Short AI clips for your edit — describe the shot, optionally start from a
          reference image. A 5-second clip takes roughly 3–8 minutes, so queue a batch
          and collect the results here later.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[5fr_4fr]">
        <div className="animate-fade-up space-y-5" style={{ "--delay": "0.08s" } as React.CSSProperties}>
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between">
              <label
                htmlFor="prompt"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Shot description
              </label>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {prompt.length.toLocaleString()} chars
              </span>
            </div>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Slow dolly across a foggy harbour at dawn, fishing boats, cinematic, shallow depth of field…"
              className="min-h-36 resize-y"
              disabled={busy}
            />
          </div>

          <ModelSelect kind="broll" value={model} onChange={setModel} disabled={busy} />

          <div className="grid gap-5 sm:grid-cols-[1fr_2fr]">
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Duration
              </label>
              <Select
                value={duration}
                onValueChange={(value) => {
                  if (value !== null) setDuration(value)
                }}
                disabled={busy}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DURATIONS.map((seconds) => (
                    <SelectItem key={seconds} value={String(seconds)}>
                      {seconds} seconds
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <FileDropzone
              label="Reference image (optional)"
              hint="Animates from this frame"
              file={image}
              onChange={setImage}
              disabled={busy}
            />
          </div>

          {submitError && (
            <Alert variant="destructive">
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          )}

          <Button
            size="lg"
            className="w-full font-mono uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !prompt.trim()}
          >
            {busy ? "Generating…" : "Generate clip"}
          </Button>
        </div>

        <div className="animate-fade-up space-y-4" style={{ "--delay": "0.16s" } as React.CSSProperties}>
          <JobProgress status={status} />
          {status?.status === "finished" && status.video && (
            <>
              <VideoPreview video={status.video} />
              <Button variant="secondary" onClick={reset} className="w-full">
                New clip
              </Button>
            </>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Your generated clip will appear here.
            </div>
          )}
        </div>
      </div>

      <RecentJobs kind="broll" refreshKey={refreshKey} />
    </div>
  );
}
