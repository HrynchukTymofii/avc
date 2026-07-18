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
import { VoiceSelect } from "@/components/voice-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { submitTalkingHead } from "@/lib/api";
import { talkingHeadCost } from "@/lib/pricing";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

export default function TalkingHeadPage() {
  return (
    <Suspense fallback={null}>
      <TalkingHeadStudio />
    </Suspense>
  );
}

// stable reference — an inline arrow would refetch the feed on every render
const withoutVoiceOvers = (job: { voiceOnly?: boolean }) => job.voiceOnly !== true;

function TalkingHeadStudio() {
  const [avatar, setAvatar] = useState<File | null>(null);
  const [model, setModel] = useState("");
  const [script, setScript] = useState("");
  const [voice, setVoice] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  // the queue takes more submissions while a job runs — only lock during the POST
  const busy = submitting;
  const cost = talkingHeadCost(model, script);

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const canSubmit = avatar !== null && script.trim() !== "" && voice !== "";

  const handleSubmit = async () => {
    if (!canSubmit || busy) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitTalkingHead({
        avatar,
        script,
        voice,
        model: model || undefined,
      });
      setJobId(response.jobId);
      setScript("");
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
        kind="talking_head"
        refreshKey={refreshKey}
        status={status}
        activeJobId={jobId}
        // narration-only jobs live on the Voice Over tab
        filterJobs={withoutVoiceOvers}
        emptyTitle="Talking Head Studio"
        emptyHint="Paste your script below, add a portrait with +, pick a voice — you get a lip-synced video. Roughly 1–3 minutes of processing per minute of script."
      />

      <StudioComposer>
        <div className="flex items-start gap-3">
          <ComposerAttach
            label="Avatar — clear front-facing portrait"
            file={avatar}
            onChange={setAvatar}
            disabled={busy}
          />
          <Textarea
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder="Paste the words your avatar should speak… add the portrait with +"
            className="max-h-56 min-h-16 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
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
        <div className="mt-1 flex flex-wrap items-center gap-2 border-t pt-2.5">
          <ComposerControl>
            <ModelSelect
              kind="talking_head"
              value={model}
              onChange={setModel}
              disabled={busy}
              compact
            />
          </ComposerControl>
          <ComposerControl label="Voice">
            <VoiceSelect value={voice} onChange={setVoice} disabled={busy} compact />
          </ComposerControl>
          {!avatar && script.trim() !== "" && (
            <span className="text-xs text-muted-foreground">
              Add a portrait with the + button to generate.
            </span>
          )}
          <Button
            size="lg"
            className="ml-auto rounded-lg font-mono text-xs uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !canSubmit}
          >
            {busy ? "Generating…" : `Generate · ${cost} cr`}
          </Button>
        </div>
      </StudioComposer>
    </Studio>
  );
}
