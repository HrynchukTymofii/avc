"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { GenerationFeed } from "@/components/generation-feed";
import { ModelSelect } from "@/components/model-select";
import {
  ComposerAttach,
  ComposerControl,
  Studio,
  StudioComposer,
} from "@/components/studio";
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
import { upscaleCost } from "@/lib/pricing";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";
import type { JobSummary } from "@/types/api";

const SCALES = [
  { value: "4", label: "4× — maximum detail" },
  { value: "2", label: "2× — smaller output" },
] as const;

const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";
const VIDEO_ACCEPT = "video/mp4,video/quicktime,video/webm";

// The nav links here as "Upscale Image" (/upscale?media=image) and "Upscale
// Video" (/upscale?media=video) — each view lists only its own media type.
// Jobs from before `media` was in the summary are classified by their output.
const jobMedia = (job: JobSummary) => job.media ?? (job.video ? "video" : "image");
const MEDIA_FILTERS: Record<"image" | "video", (job: JobSummary) => boolean> = {
  image: (job) => jobMedia(job) === "image",
  video: (job) => jobMedia(job) === "video",
};

export default function UpscalePage() {
  return (
    <Suspense fallback={null}>
      <UpscaleStudio />
    </Suspense>
  );
}

function UpscaleStudio() {
  const mediaParam = useSearchParams().get("media");
  const media = mediaParam === "image" || mediaParam === "video" ? mediaParam : null;
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [scale, setScale] = useState<string>("4");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  // the queue takes more submissions while a job runs — only lock during the POST
  const busy = submitting;
  const cost = upscaleCost(file?.type.startsWith("video/") ? "video" : "image");

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const handleSubmit = async () => {
    if (!file || busy) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitUpscale({
        file,
        model: model || undefined,
        scale: Number(scale),
      });
      setJobId(response.jobId);
      setFile(null);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Studio>
      <GenerationFeed
        kind="upscale"
        refreshKey={refreshKey}
        status={status}
        activeJobId={jobId}
        filterJobs={media ? MEDIA_FILTERS[media] : undefined}
        emptyTitle={
          media === "video"
            ? "Video Upscaler"
            : media === "image"
              ? "Image Upscaler"
              : "Upscaler"
        }
        emptyHint={
          media === "video"
            ? "Add a short video with + and enlarge it with Real-ESRGAN. Tip: you can also upscale any generation straight from its tile in the Library."
            : media === "image"
              ? "Add an image with + and enlarge it with Real-ESRGAN. Tip: you can also upscale any generation straight from its tile in the Library."
              : "Add an image or a short video with + and enlarge it with Real-ESRGAN. Tip: you can also upscale any generation straight from its tile in the Library."
        }
      />

      <StudioComposer>
        <div className="flex items-center gap-3">
          <ComposerAttach
            label={
              media === "video"
                ? "Video to upscale"
                : media === "image"
                  ? "Image to upscale"
                  : "Image or video to upscale"
            }
            file={file}
            onChange={setFile}
            accept={
              media === "video"
                ? VIDEO_ACCEPT
                : media === "image"
                  ? IMAGE_ACCEPT
                  : `${IMAGE_ACCEPT},${VIDEO_ACCEPT}`
            }
            disabled={busy}
          />
          <p className="flex-1 text-sm text-muted-foreground">
            {file
              ? `${file.name} · ${(file.size / 1_000_000).toFixed(1)} MB`
              : media === "video"
                ? "MP4/MOV/WebM ≤ 200 MB, ≤ 2 min"
                : media === "image"
                  ? "PNG/JPEG/WebP ≤ 20 MB"
                  : "PNG/JPEG ≤ 20 MB · MP4/MOV/WebM ≤ 200 MB, ≤ 2 min"}
          </p>
        </div>
        {submitError && (
          <Alert variant="destructive" className="my-2">
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-2.5">
          <ComposerControl>
            <ModelSelect kind="upscale" value={model} onChange={setModel} disabled={busy} compact />
          </ComposerControl>
          <ComposerControl>
            <Select
              value={scale}
              onValueChange={(value) => {
                if (value !== null) setScale(value);
              }}
              disabled={busy}
              items={Object.fromEntries(SCALES.map((s) => [s.value, s.label]))}
            >
              <SelectTrigger size="sm">
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
          </ComposerControl>
          <Button
            size="lg"
            className="ml-auto rounded-lg font-mono text-xs uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !file}
          >
            {busy ? "Upscaling…" : `Upscale · ${cost} cr`}
          </Button>
        </div>
      </StudioComposer>
    </Studio>
  );
}
