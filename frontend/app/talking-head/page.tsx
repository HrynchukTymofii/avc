"use client";

import { useEffect, useRef, useState } from "react";

import { FileDropzone } from "@/components/file-dropzone";
import { JobProgress } from "@/components/job-progress";
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
import { getVoices, submitTalkingHead } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";
import type { Voice } from "@/types/api";

export default function TalkingHeadPage() {
  const [avatar, setAvatar] = useState<File | null>(null);
  const [script, setScript] = useState("");
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voice, setVoice] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  const busy = submitting || (jobId !== null && !isTerminal(status));

  useEffect(() => {
    getVoices()
      .then((response) => {
        setVoices(response.voices);
        if (response.voices.length > 0) setVoice(response.voices[0].id);
      })
      .catch(() => setVoices([]));
  }, []);

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const handleSubmit = async () => {
    if (!avatar || !script.trim() || !voice) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitTalkingHead({ avatar, script, voice });
      setJobId(response.jobId);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setJobId(null);
    setScript("");
    setAvatar(null);
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Talking Head Studio</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Upload a portrait, pick a voice, paste your script — get a lip-synced video.
          Expect roughly 1–3 minutes of processing per minute of script.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[5fr_4fr]">
        <div className="animate-fade-up space-y-5" style={{ "--delay": "0.08s" } as React.CSSProperties}>
          <FileDropzone
            label="Avatar"
            hint="PNG / JPEG · clear front-facing portrait"
            file={avatar}
            onChange={setAvatar}
            disabled={busy}
          />

          <div className="space-y-1.5">
            <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Voice
            </label>
            <Select value={voice} onValueChange={setVoice} disabled={busy || !voices?.length}>
              <SelectTrigger className="w-full">
                <SelectValue
                  placeholder={voices === null ? "Loading voices…" : "No voices available"}
                />
              </SelectTrigger>
              <SelectContent>
                {voices?.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name}
                    <span className="ml-2 font-mono text-[10px] uppercase text-muted-foreground">
                      {item.language}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {voices?.length === 0 && (
              <p className="text-xs text-destructive">
                No voices configured — add reference clips on the server
                (backend/assets/voices).
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between">
              <label
                htmlFor="script"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Script
              </label>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {script.length.toLocaleString()} chars
              </span>
            </div>
            <Textarea
              id="script"
              value={script}
              onChange={(event) => setScript(event.target.value)}
              placeholder="Paste the words your avatar should speak…"
              className="min-h-56 resize-y"
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
            disabled={busy || !avatar || !script.trim() || !voice}
          >
            {busy ? "Generating…" : "Generate video"}
          </Button>
        </div>

        <div className="animate-fade-up space-y-4" style={{ "--delay": "0.16s" } as React.CSSProperties}>
          <JobProgress status={status} />
          {status?.status === "finished" && (
            <>
              <VideoPreview video={status.video} audio={status.audio} />
              <Button variant="secondary" onClick={reset} className="w-full">
                New generation
              </Button>
            </>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Your generated video will appear here.
            </div>
          )}
        </div>
      </div>

      <RecentJobs kind="talking_head" refreshKey={refreshKey} />
    </div>
  );
}
