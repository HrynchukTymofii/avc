"use client";

import { useEffect, useRef, useState } from "react";

import { GenerationFeed } from "@/components/generation-feed";
import { ModelSelect } from "@/components/model-select";
import { ComposerControl, Studio, StudioComposer } from "@/components/studio";
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
  { value: "landscape", label: "Landscape" },
  { value: "portrait", label: "Portrait" },
  { value: "square", label: "Square" },
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
    if (!prompt.trim() || busy) return;
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
      setPrompt("");
      setRefreshKey((key) => key + 1); // show the queued job in the feed
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Studio>
      <GenerationFeed
        kind="image"
        refreshKey={refreshKey}
        status={status}
        emptyTitle="Image Generator"
        emptyHint="Describe the scene below and pick a format — your images appear here, newest at the bottom. Under a minute per image once the model is warm."
      />

      <StudioComposer>
        <Textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Describe the image… e.g. a cozy study with warm lamplight, bookshelves, photorealistic"
          className="max-h-48 min-h-16 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
          disabled={busy}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              void handleSubmit();
            }
          }}
        />
        {submitError && (
          <Alert variant="destructive" className="mb-2">
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t pt-2.5">
          <ComposerControl>
            <ModelSelect kind="image" value={model} onChange={setModel} disabled={busy} compact />
          </ComposerControl>
          <ComposerControl>
            <Select
              value={orientation}
              onValueChange={(value) => {
                if (value !== null) setOrientation(value);
              }}
              disabled={busy}
              items={Object.fromEntries(ORIENTATIONS.map((o) => [o.value, o.label]))}
            >
              <SelectTrigger size="sm">
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
          </ComposerControl>
          <ComposerControl>
            <Select
              value={count}
              onValueChange={(value) => {
                if (value !== null) setCount(value);
              }}
              disabled={busy}
              items={Object.fromEntries(
                COUNTS.map((c) => [c, c === "1" ? "1 image" : `${c} images`]),
              )}
            >
              <SelectTrigger size="sm">
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
          </ComposerControl>
          {model === "wan-5b" && (
            <ComposerControl>
              <StyleSelect value={lora} onChange={setLora} disabled={busy} compact />
            </ComposerControl>
          )}
          <Button
            className="ml-auto font-mono text-xs uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !prompt.trim()}
          >
            {busy ? "Generating…" : "Generate"}
          </Button>
        </div>
      </StudioComposer>
    </Studio>
  );
}
