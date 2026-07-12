"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { FileDropzone } from "@/components/file-dropzone";
import { JobProgress } from "@/components/job-progress";
import { MultiFileDropzone } from "@/components/multi-file-dropzone";
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
import { getVoices, submitFullVideo } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";
import type { Voice } from "@/types/api";

const ORIENTATIONS = [
  { id: "landscape", label: "Landscape · 1280×704" },
  { id: "portrait", label: "Portrait · 704×1280" },
  { id: "square", label: "Square · 960×960" },
] as const;

const VISUAL_MARKER = /\[\s*(b[ -]?roll|image|clip|on[ -]?camera)\s*(?::([^\]]*))?\]/gi;

/** Mirror of the backend parser's semantics, just close enough to drive the
 * submit button: which [CLIP: …] names the script references, and whether any
 * on-camera narration exists (text before the first marker, or [ONCAMERA]). */
function analyzeScript(script: string): { clipRefs: string[]; needsAvatar: boolean } {
  const clipRefs: string[] = [];
  let firstMarker = script.length;
  let hasOncamera = false;
  for (const match of script.matchAll(VISUAL_MARKER)) {
    firstMarker = Math.min(firstMarker, match.index ?? 0);
    const keyword = match[1].replace(/[ -]/g, "").toLowerCase();
    if (keyword === "clip" && match[2]?.trim()) clipRefs.push(match[2].trim());
    if (keyword === "oncamera") hasOncamera = true;
  }
  return {
    clipRefs,
    needsAvatar: hasOncamera || script.slice(0, firstMarker).trim() !== "",
  };
}

export default function FullVideoPage() {
  const [script, setScript] = useState("");
  const [avatar, setAvatar] = useState<File | null>(null);
  const [clips, setClips] = useState<File[]>([]);
  const [orientation, setOrientation] = useState<string>("landscape");
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

  const { clipRefs, needsAvatar } = useMemo(() => analyzeScript(script), [script]);
  const missingClips = useMemo(() => {
    const uploaded = new Set(clips.map((file) => file.name.toLowerCase()));
    return clipRefs.filter((name) => !uploaded.has(name.toLowerCase()));
  }, [clipRefs, clips]);

  const canSubmit =
    script.trim() !== "" &&
    voice !== "" &&
    (!needsAvatar || avatar !== null) &&
    missingClips.length === 0;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitFullVideo({
        script,
        voice,
        avatar: needsAvatar ? avatar : null,
        orientation,
        clips,
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
    setScript("");
    setAvatar(null);
    setClips([]);
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Full Video Studio</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          One tagged script in, one finished video out: your talking head on camera,
          AI b-roll, AI stills and your own clips — cut together over a continuous
          voiceover.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[5fr_4fr]">
        <div
          className="animate-fade-up space-y-5"
          style={{ "--delay": "0.08s" } as React.CSSProperties}
        >
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between">
              <label
                htmlFor="script"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Tagged script
              </label>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {script.length.toLocaleString()} chars
              </span>
            </div>
            <Textarea
              id="script"
              value={script}
              onChange={(event) => setScript(event.target.value)}
              placeholder={
                "Plain text is spoken on camera…\n\n" +
                "[BROLL: aerial shot of a coastline at dawn]\n" +
                "…this narration plays over AI footage.\n\n" +
                "[ONCAMERA]\n…and now back to you."
              }
              className="min-h-56 resize-y"
              disabled={busy}
            />
            <details className="rounded-md border bg-card px-3 py-2 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-widest">
                Marker syntax
              </summary>
              <ul className="mt-2 space-y-1 font-mono text-[11px] leading-relaxed">
                <li>
                  <span className="text-foreground">[BROLL: prompt]</span> — cut to an AI
                  video clip
                </li>
                <li>
                  <span className="text-foreground">[IMAGE: prompt]</span> — cut to an AI
                  still with a slow zoom
                </li>
                <li>
                  <span className="text-foreground">[CLIP: filename.mp4]</span> — cut to an
                  uploaded clip (muted)
                </li>
                <li>
                  <span className="text-foreground">[ONCAMERA]</span> — return to the
                  talking head
                </li>
                <li className="pt-1 text-muted-foreground/80">
                  Voice tags like [short pause] or [excited] still work — anything
                  without a colon is spoken direction, not a cut.
                </li>
              </ul>
            </details>
          </div>

          <FileDropzone
            label="Avatar"
            hint={
              needsAvatar
                ? "PNG / JPEG · clear front-facing portrait"
                : "Not needed — no on-camera segments in the script"
            }
            file={avatar}
            onChange={setAvatar}
            disabled={busy || !needsAvatar}
          />

          <MultiFileDropzone
            label="Clips"
            hint="MP4 / MOV / WebM · referenced from the script as [CLIP: name]"
            accept={["video/mp4", "video/quicktime", "video/webm"]}
            maxMb={200}
            files={clips}
            onChange={setClips}
            disabled={busy}
          />
          {missingClips.length > 0 && (
            <p className="text-xs text-destructive">
              The script references clips that are not uploaded yet:{" "}
              {missingClips.join(", ")}
            </p>
          )}

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Voice
              </label>
              <Select
                value={voice}
                onValueChange={(value) => {
                  if (value !== null) setVoice(value);
                }}
                disabled={busy || !voices?.length}
              >
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
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Canvas
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
                  {ORIENTATIONS.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-muted-foreground/70">
                Pick portrait for portrait avatars — every segment is cropped to
                this canvas.
              </p>
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
            disabled={busy || !canSubmit}
          >
            {busy ? "Generating…" : "Generate full video"}
          </Button>
        </div>

        <div
          className="animate-fade-up space-y-4"
          style={{ "--delay": "0.16s" } as React.CSSProperties}
        >
          <JobProgress status={status} />
          {status?.status === "processing" && status.audio && (
            <div className="animate-fade-up rounded-lg border bg-card p-3">
              <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                Voiceover ready — visuals still rendering
              </p>
              <audio src={status.audio} controls className="w-full" />
              <Button
                size="sm"
                variant="secondary"
                className="mt-2"
                render={<a href={status.audio} download />}
              >
                Download audio
              </Button>
            </div>
          )}
          {status?.status === "finished" && (
            <>
              {status.video && <VideoPreview video={status.video} audio={status.audio} />}
              <Button variant="secondary" onClick={reset} className="w-full">
                New generation
              </Button>
            </>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Your assembled video will appear here.
            </div>
          )}
        </div>
      </div>

      <RecentJobs kind="full_video" refreshKey={refreshKey} />
    </div>
  );
}
