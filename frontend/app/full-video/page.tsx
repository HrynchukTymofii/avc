"use client";

import { SlidersHorizontalIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { FileDropzone } from "@/components/file-dropzone";
import { GenerationFeed } from "@/components/generation-feed";
import { MultiFileDropzone } from "@/components/multi-file-dropzone";
import {
  AdvancedPanel,
  ComposerControl,
  Studio,
  StudioComposer,
} from "@/components/studio";
import { VoiceSelect } from "@/components/voice-select";
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
import { submitFullVideo } from "@/lib/api";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";

const ORIENTATIONS = [
  { id: "landscape", label: "Landscape" },
  { id: "portrait", label: "Portrait" },
  { id: "square", label: "Square" },
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
  const [voice, setVoice] = useState<string>("");
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

  const blocker =
    script.trim() === ""
      ? null
      : needsAvatar && avatar === null
        ? "Add an avatar in Setup — the script has on-camera narration."
        : missingClips.length > 0
          ? `Upload the referenced clips in Setup: ${missingClips.join(", ")}`
          : null;

  const handleSubmit = async () => {
    if (!canSubmit || busy) return;
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
      setScript("");
      setClips([]);
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
        kind="full_video"
        refreshKey={refreshKey}
        status={status}
        emptyTitle="Full Video Studio"
        emptyHint="One tagged script in, one finished video out: talking head on camera, AI b-roll ([BROLL: …]), AI stills ([IMAGE: …]) and your own clips ([CLIP: file.mp4]) — cut together over a continuous voiceover."
      />

      <AdvancedPanel open={panelOpen} onClose={() => setPanelOpen(false)} title="Setup">
        <VoiceSelect value={voice} onChange={setVoice} disabled={busy} />
        <FileDropzone
          label="Avatar (on-camera segments)"
          hint="PNG / JPEG · clear front-facing portrait"
          file={avatar}
          onChange={setAvatar}
          disabled={busy}
        />
        <MultiFileDropzone
          label="Your clips ([CLIP: …])"
          hint="MP4 / MOV / WebM · matched to the script by file name"
          accept={["video/mp4", "video/quicktime", "video/webm"]}
          maxMb={200}
          files={clips}
          onChange={setClips}
          disabled={busy}
        />
      </AdvancedPanel>

      <StudioComposer>
        <Textarea
          value={script}
          onChange={(event) => setScript(event.target.value)}
          placeholder={
            "Write your tagged script…\nIntro spoken on camera. [BROLL: aerial city at dawn] Voiceover over AI footage. [CLIP: demo.mp4] Voiceover over your clip."
          }
          className="max-h-64 min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
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
            <Select
              value={orientation}
              onValueChange={(value) => {
                if (value !== null) setOrientation(value);
              }}
              disabled={busy}
              items={Object.fromEntries(ORIENTATIONS.map((o) => [o.id, o.label]))}
            >
              <SelectTrigger size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ORIENTATIONS.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </ComposerControl>
          <Button
            size="sm"
            variant={avatar || clips.length > 0 ? "secondary" : "ghost"}
            onClick={() => setPanelOpen((open) => !open)}
          >
            <SlidersHorizontalIcon className="size-3.5" />
            Setup
          </Button>
          {blocker && <span className="text-xs text-muted-foreground">{blocker}</span>}
          <Button
            className="ml-auto font-mono text-xs uppercase tracking-widest"
            onClick={handleSubmit}
            disabled={busy || !canSubmit}
          >
            {busy ? "Generating…" : "Generate"}
          </Button>
        </div>
      </StudioComposer>
    </Studio>
  );
}
