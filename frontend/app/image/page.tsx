"use client";

import { useEffect, useRef, useState } from "react";

import { JobProgress } from "@/components/job-progress";
import { ModelSelect } from "@/components/model-select";
import { RecentJobs } from "@/components/recent-jobs";
import { StyleSelect } from "@/components/style-select";
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
import { submitImage } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const ORIENTATIONS = [
  { value: "landscape", label: "Landscape · 1280×704" },
  { value: "portrait", label: "Portrait · 704×1280" },
  { value: "square", label: "Square · 960×960" },
] as const;

const COUNTS = ["1", "2", "3", "4"] as const;

export default function ImagePage() {
  const [prompt, setPrompt] = useState("");
  const [orientation, setOrientation] = useState<string>("landscape");
  const [model, setModel] = useState("");
  const [count, setCount] = useState<string>("1");
  const [lora, setLora] = useState("");
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
      const response = await submitImage({
        prompt,
        orientation,
        model: model || undefined,
        count: Number(count),
        // styles are trained on (and only apply to) the Wan2.2 5B engine
        lora: model === "wan-5b" ? lora || undefined : undefined,
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
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Image Generator</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Still images from the same model that renders your B-roll — describe the
          scene and pick a format. An image takes under a minute once the model is
          warm (a few minutes on the first run).
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
                Scene description
              </label>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {prompt.length.toLocaleString()} chars
              </span>
            </div>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="A cozy study with warm lamplight, bookshelves, a steaming cup of tea on a wooden desk, photorealistic…"
              className="min-h-36 resize-y"
              disabled={busy}
            />
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <ModelSelect kind="image" value={model} onChange={setModel} disabled={busy} />
            <StyleSelect
              value={model === "wan-5b" ? lora : ""}
              onChange={setLora}
              disabled={busy || model !== "wan-5b"}
            />
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Format
              </label>
              <Select
                value={orientation}
                onValueChange={(value) => {
                  if (value !== null) setOrientation(value);
                }}
                disabled={busy}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ORIENTATIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Variations
              </label>
              <Select
                value={count}
                onValueChange={(value) => {
                  if (value !== null) setCount(value);
                }}
                disabled={busy}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {COUNTS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option === "1" ? "1 image" : `${option} images`}
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
            disabled={busy || !prompt.trim()}
          >
            {busy ? "Generating…" : "Generate image"}
          </Button>
        </div>

        <div className="animate-fade-up space-y-4" style={{ "--delay": "0.16s" } as React.CSSProperties}>
          <JobProgress status={status} />
          {status?.status === "finished" && status.image && (
            <>
              {(status.images ?? [status.image]).map((url, index) => (
                <div key={url} className="overflow-hidden rounded-lg border bg-black">
                  <a href={url} target="_blank" rel="noreferrer">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={url} alt={`Generated image ${index + 1}`} className="w-full" />
                  </a>
                  <div className="flex items-center justify-between px-3 py-2">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      Variation {index + 1}
                    </span>
                    <Button size="sm" variant="secondary" render={<a href={url} download />}>
                      Download
                    </Button>
                  </div>
                </div>
              ))}
              <Button variant="secondary" onClick={reset} className="w-full">
                New image
              </Button>
            </>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Your generated image will appear here.
            </div>
          )}
        </div>
      </div>

      <RecentJobs kind="image" refreshKey={refreshKey} />
    </div>
  );
}
