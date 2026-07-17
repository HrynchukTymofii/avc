"use client";

import { useEffect, useRef, useState } from "react";

import { GenerationFeed } from "@/components/generation-feed";
import { MediaDropzone } from "@/components/media-dropzone";
import { ModelSelect } from "@/components/model-select";
import { ComposerControl, Studio, StudioComposer } from "@/components/studio";
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
        emptyTitle="Upscaler"
        emptyHint="Drop an image or a short video below and enlarge it with Real-ESRGAN. Tip: you can also upscale any generation straight from the Library — no re-upload."
      />

      <StudioComposer>
        <MediaDropzone
          label="Image or video"
          hint="PNG/JPEG ≤ 20 MB · MP4/MOV/WebM ≤ 200 MB, ≤ 2 min"
          file={file}
          onChange={setFile}
          maxImageMb={20}
          maxVideoMb={200}
          disabled={busy}
        />
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
            className="ml-auto font-mono text-xs uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !file}
          >
            {busy ? "Upscaling…" : "Upscale"}
          </Button>
        </div>
      </StudioComposer>
    </Studio>
  );
}
