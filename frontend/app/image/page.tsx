"use client";

import { Suspense, useEffect, useRef, useState } from "react";

import { GenerationFeed } from "@/components/generation-feed";
import { ModelSelect } from "@/components/model-select";
import {
  ComposerAttach,
  ComposerControl,
  Studio,
  StudioComposer,
} from "@/components/studio";
import { StyleScaleSelect, StyleSelect } from "@/components/style-select";
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
import { imageCost } from "@/lib/pricing";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const ORIENTATIONS = [
  { value: "landscape", label: "Landscape" },
  { value: "portrait", label: "Portrait" },
  { value: "square", label: "Square" },
] as const;

const COUNTS = ["1", "2", "3", "4"] as const;

// Kontext guidance presets: how strongly the prompt pulls away from the reference.
const GUIDANCES = [
  { value: "1.8", label: "Close to reference" },
  { value: "2.5", label: "Balanced edit" },
  { value: "3.5", label: "Strong change" },
] as const;

export default function ImagePage() {
  return (
    <Suspense fallback={null}>
      <ImageStudio />
    </Suspense>
  );
}

function ImageStudio() {
  const [prompt, setPrompt] = useState("");
  const [orientation, setOrientation] = useState<string>("landscape");
  const [model, setModel] = useState("");
  const [count, setCount] = useState<string>("1");
  const [lora, setLora] = useState("");
  const [loraScale, setLoraScale] = useState("1.0");
  const [image, setImage] = useState<File | null>(null);
  const [guidance, setGuidance] = useState<string>("2.5");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  // the queue takes more submissions while a job runs — only lock during the POST
  const busy = submitting;
  const cost = imageCost(model, Number(count));
  // Kontext edits an existing image — a reference upload is required.
  const needsReference = model === "flux-kontext";

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const handleSubmit = async () => {
    if (!prompt.trim() || busy || (needsReference && !image)) return;
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
        loraScale: model === "wan-5b" && lora ? Number(loraScale) : undefined,
        image: needsReference ? image : undefined,
        guidance: needsReference ? Number(guidance) : undefined,
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
        activeJobId={jobId}
        emptyTitle="Image Generator"
        emptyHint="Describe the scene below and pick a format — your images appear here, newest at the bottom. Under a minute per image once the model is warm."
      />

      <StudioComposer>
        <div className="flex items-start gap-3">
          {needsReference && (
            <ComposerAttach
              label="Reference image (the character/subject to edit)"
              file={image}
              onChange={setImage}
              disabled={busy}
            />
          )}
          <Textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={
              needsReference
                ? "Describe the change… e.g. show this character from behind, doing pull-ups on a street bar"
                : "Describe the image… e.g. a cozy study with warm lamplight, bookshelves, photorealistic"
            }
            className="max-h-48 min-h-16 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
            disabled={busy}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                void handleSubmit();
              }
            }}
          />
        </div>
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
          <div className="ml-auto flex items-center gap-2">
            {model === "wan-5b" && (
              <>
                <StyleSelect value={lora} onChange={setLora} disabled={busy} tile />
                {lora && (
                  <StyleScaleSelect value={loraScale} onChange={setLoraScale} disabled={busy} />
                )}
              </>
            )}
            {needsReference && (
              <Select
                value={guidance}
                onValueChange={(value) => {
                  if (value !== null) setGuidance(value);
                }}
                disabled={busy}
                items={Object.fromEntries(GUIDANCES.map((g) => [g.value, g.label]))}
              >
                <SelectTrigger size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {GUIDANCES.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Button
              size="lg"
              className="rounded-lg font-mono text-xs uppercase tracking-widest"
              onClick={handleSubmit}
              disabled={busy || !prompt.trim() || (needsReference && !image)}
            >
              {busy ? "Generating…" : `Generate · ${cost} cr`}
            </Button>
          </div>
        </div>
      </StudioComposer>
    </Studio>
  );
}
