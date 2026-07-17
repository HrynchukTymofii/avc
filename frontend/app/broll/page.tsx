"use client";

import { SlidersHorizontalIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { FileDropzone } from "@/components/file-dropzone";
import { GenerationFeed } from "@/components/generation-feed";
import { ModelSelect } from "@/components/model-select";
import {
  AdvancedPanel,
  ComposerControl,
  Studio,
  StudioComposer,
} from "@/components/studio";
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
import { submitBroll } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const DURATIONS = [3, 4, 5] as const;

export default function BrollPage() {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState<string>("5");
  const [image, setImage] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [lora, setLora] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
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
      const response = await submitBroll({
        prompt,
        duration: Number(duration),
        image,
        model: model || undefined,
        lora: model === "wan-5b" ? lora || undefined : undefined,
      });
      setJobId(response.jobId);
      setPrompt("");
      setImage(null);
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
        kind="broll"
        refreshKey={refreshKey}
        status={status}
        emptyTitle="B-Roll Generator"
        emptyHint="Describe the shot below — short AI clips for your edit. A 5-second clip takes roughly 3–8 minutes, so queue a batch and collect the results here."
      />

      <AdvancedPanel open={panelOpen} onClose={() => setPanelOpen(false)} title="Advanced">
        <FileDropzone
          label="Reference image (optional)"
          hint="Animates from this frame"
          file={image}
          onChange={setImage}
          disabled={busy}
        />
      </AdvancedPanel>

      <StudioComposer>
        <Textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Describe the shot… e.g. slow dolly across a foggy harbour at dawn, cinematic"
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
            <ModelSelect kind="broll" value={model} onChange={setModel} disabled={busy} compact />
          </ComposerControl>
          <ComposerControl>
            <Select
              value={duration}
              onValueChange={(value) => {
                if (value !== null) setDuration(value);
              }}
              disabled={busy}
              items={Object.fromEntries(DURATIONS.map((s) => [String(s), `${s} s`]))}
            >
              <SelectTrigger size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DURATIONS.map((seconds) => (
                  <SelectItem key={seconds} value={String(seconds)}>
                    {seconds} s
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
            size="sm"
            variant={image ? "secondary" : "ghost"}
            onClick={() => setPanelOpen((open) => !open)}
            title="Reference image"
          >
            <SlidersHorizontalIcon className="size-3.5" />
            {image ? "1 ref" : "Advanced"}
          </Button>
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
