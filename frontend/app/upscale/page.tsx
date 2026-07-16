"use client";

import { useEffect, useRef, useState } from "react";

import { JobProgress } from "@/components/job-progress";
import { MediaDropzone } from "@/components/media-dropzone";
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
import { submitUpscale } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const SCALES = [
  { value: "4", label: "4× — maximum detail" },
  { value: "2", label: "2× — smaller output" },
] as const;

export default function UpscalePage() {
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [scale, setScale] = useState<string>("4");
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
    if (!file) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitUpscale({
        file,
        model: model || undefined,
        scale: Number(scale),
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
    setFile(null);
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Upscaler</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Sharpen and enlarge images or short videos with Real-ESRGAN. Pick the
          drawn/anime model for stylized art and generated characters — the photo
          model for everything else. Images finish in seconds; videos are upscaled
          frame by frame (roughly a minute of processing per second of footage).
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[5fr_4fr]">
        <div
          className="animate-fade-up space-y-5"
          style={{ "--delay": "0.08s" } as React.CSSProperties}
        >
          <MediaDropzone
            label="Image or video"
            hint="PNG/JPEG ≤ 20 MB · MP4/MOV/WebM ≤ 200 MB, ≤ 2 min"
            file={file}
            onChange={setFile}
            maxImageMb={20}
            maxVideoMb={200}
            disabled={busy}
          />

          <div className="grid gap-5 sm:grid-cols-2">
            <ModelSelect kind="upscale" value={model} onChange={setModel} disabled={busy} />
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Scale
              </label>
              <Select
                value={scale}
                onValueChange={(value) => {
                  if (value !== null) setScale(value);
                }}
                disabled={busy}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCALES.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
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
            disabled={busy || !file}
          >
            {busy ? "Upscaling…" : "Upscale"}
          </Button>
        </div>

        <div
          className="animate-fade-up space-y-4"
          style={{ "--delay": "0.16s" } as React.CSSProperties}
        >
          <JobProgress status={status} />
          {status?.status === "finished" && status.video && (
            <>
              <VideoPreview video={status.video} />
              <Button variant="secondary" onClick={reset} className="w-full">
                Upscale another
              </Button>
            </>
          )}
          {status?.status === "finished" && status.image && (
            <>
              <div className="overflow-hidden rounded-lg border bg-black">
                <a href={status.image} target="_blank" rel="noreferrer">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={status.image} alt="Upscaled image" className="w-full" />
                </a>
                <div className="flex items-center justify-between px-3 py-2">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Upscaled {scale}×
                  </span>
                  <Button size="sm" variant="secondary" render={<a href={status.image} download />}>
                    Download
                  </Button>
                </div>
              </div>
              <Button variant="secondary" onClick={reset} className="w-full">
                Upscale another
              </Button>
            </>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Your upscaled file will appear here.
            </div>
          )}
        </div>
      </div>

      <RecentJobs kind="upscale" refreshKey={refreshKey} />
    </div>
  );
}
