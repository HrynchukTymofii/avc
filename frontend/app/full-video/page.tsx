"use client";

import { CheckIcon, UploadIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { GenerationFeed } from "@/components/generation-feed";
import {
  ComposerAttach,
  ComposerControl,
  Studio,
  StudioComposer,
} from "@/components/studio";
import { VoiceSelect } from "@/components/voice-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { submitFullVideo } from "@/lib/api";
import { fullVideoCost } from "@/lib/pricing";
import { cn } from "@/lib/utils";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";
import { stageLabel } from "@/types/api";

const ORIENTATIONS = [
  { id: "landscape", label: "Landscape" },
  { id: "portrait", label: "Portrait" },
  { id: "square", label: "Square" },
] as const;

const VISUAL_MARKER = /\[\s*(b[ -]?roll|image|clip|on[ -]?camera)\s*(?::([^\]]*))?\]/gi;

interface Scene {
  kind: "oncamera" | "broll" | "image" | "clip";
  /** BROLL/IMAGE prompt or CLIP file name (as written in the script). */
  visual: string;
  /** Narration spoken over this scene. */
  text: string;
}

/** Client-side mirror of the backend script parser — close enough to preview
 * the scene sequence and gate the submit button. */
function parseScenes(script: string): Scene[] {
  const scenes: Scene[] = [];
  const matches = [...script.matchAll(VISUAL_MARKER)];
  const preText = script.slice(0, matches[0]?.index ?? script.length).trim();
  if (preText) scenes.push({ kind: "oncamera", visual: "", text: preText });
  matches.forEach((match, index) => {
    const keyword = match[1].replace(/[ -]/g, "").toLowerCase();
    const text = script
      .slice(match.index! + match[0].length, matches[index + 1]?.index ?? script.length)
      .trim();
    scenes.push({
      kind: keyword === "oncamera" ? "oncamera" : (keyword as Scene["kind"]),
      visual: (match[2] ?? "").trim(),
      text,
    });
  });
  return scenes;
}

const SCENE_STYLES: Record<Scene["kind"], { label: string; className: string }> = {
  oncamera: { label: "On camera", className: "text-primary border-primary/40" },
  broll: { label: "B-roll", className: "text-cyan-400 border-cyan-400/40" },
  image: { label: "Image", className: "text-violet-400 border-violet-400/40" },
  clip: { label: "Your clip", className: "text-amber-400 border-amber-400/40" },
};

export default function FullVideoPage() {
  const [script, setScript] = useState("");
  const [avatar, setAvatar] = useState<File | null>(null);
  // uploaded [CLIP: …] files, keyed by the lowercased name from the script
  const [clips, setClips] = useState<Record<string, File>>({});
  const [orientation, setOrientation] = useState<string>("landscape");
  const [voice, setVoice] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const status = useJobPolling(jobId);
  // the queue takes more submissions while a job runs — only lock during the POST
  const busy = submitting;

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
    }
  }, [jobId, status]);

  const scenes = useMemo(() => parseScenes(script), [script]);
  const needsAvatar = scenes.some((scene) => scene.kind === "oncamera");
  const clipScenes = scenes.filter((scene) => scene.kind === "clip" && scene.visual);
  const missingClips = clipScenes.filter(
    (scene) => !clips[scene.visual.toLowerCase()],
  );
  const cost = fullVideoCost(script, scenes);

  const canSubmit =
    script.trim() !== "" &&
    voice !== "" &&
    (!needsAvatar || avatar !== null) &&
    missingClips.length === 0;

  const blocker =
    script.trim() === ""
      ? null
      : needsAvatar && avatar === null
        ? "Add your portrait with the + button — the script has on-camera scenes."
        : missingClips.length > 0
          ? "Upload the missing clips on their scenes above."
          : null;

  const attachClip = (clipName: string, file: File | null) => {
    setClips((current) => {
      const next = { ...current };
      if (file === null) {
        delete next[clipName.toLowerCase()];
      } else {
        // the backend matches clips to the script by file name — rename the
        // upload so it always matches the [CLIP: …] it was dropped on
        next[clipName.toLowerCase()] = new File([file], clipName, { type: file.type });
      }
      return next;
    });
  };

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
        clips: Object.values(clips),
      });
      setJobId(response.jobId);
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
        activeJobId={jobId}
        emptyTitle="Full Video Studio"
        emptyHint="One tagged script in, one finished video out. Write narration and drop in [BROLL: …], [IMAGE: …], [CLIP: file.mp4] or [ONCAMERA] markers — the scenes appear below as you type."
      />

      <StudioComposer>
        {/* scene sequence, derived live from the script */}
        {scenes.length > 0 && (
          <div className="mb-2 flex gap-2 overflow-x-auto pb-1.5">
            {scenes.map((scene, index) => {
              const style = SCENE_STYLES[scene.kind];
              const uploaded =
                scene.kind === "clip" && scene.visual
                  ? clips[scene.visual.toLowerCase()]
                  : undefined;
              return (
                <div
                  key={`${index}-${scene.kind}-${scene.visual}`}
                  className={cn(
                    "w-44 shrink-0 rounded-lg border bg-secondary/30 p-2",
                    style.className,
                  )}
                >
                  <p className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider">
                    <span>
                      {index + 1} · {style.label}
                    </span>
                  </p>
                  {scene.visual && scene.kind !== "clip" && (
                    <p
                      className="mt-1 line-clamp-2 text-xs text-foreground/85"
                      title={scene.visual}
                    >
                      {scene.visual}
                    </p>
                  )}
                  {scene.kind === "clip" && scene.visual && (
                    <ClipSlot
                      clipName={scene.visual}
                      file={uploaded}
                      disabled={busy}
                      onChange={(file) => attachClip(scene.visual, file)}
                    />
                  )}
                  {scene.text && (
                    <p
                      className="mt-1 line-clamp-2 text-[11px] text-muted-foreground"
                      title={scene.text}
                    >
                      {scene.text}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* generation progress across the scenes */}
        {busy && status && status.status === "processing" && (
          <div className="mb-2 space-y-1">
            <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              <span>{stageLabel(status.stage)}</span>
              <span className="tabular-nums">{status.progress}%</span>
            </div>
            <Progress value={status.progress} className="h-1" />
          </div>
        )}

        <div className="flex items-start gap-3">
          <ComposerAttach
            label="Avatar for on-camera scenes"
            file={avatar}
            onChange={setAvatar}
            disabled={busy}
          />
          <Textarea
            value={script}
            onChange={(event) => setScript(event.target.value)}
            placeholder={
              "Write your tagged script…\nIntro spoken on camera. [BROLL: aerial city at dawn] Voiceover over AI footage. [CLIP: demo.mp4] Voiceover over your clip."
            }
            className="max-h-64 min-h-20 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
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
          <ComposerControl label="Voice">
            <VoiceSelect value={voice} onChange={setVoice} disabled={busy} compact />
          </ComposerControl>
          {blocker && <span className="text-xs text-muted-foreground">{blocker}</span>}
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

/** Per-scene upload slot for [CLIP: …] scenes — the file is renamed to the
 * clip name from the script so the backend always matches it. */
function ClipSlot({
  clipName,
  file,
  disabled,
  onChange,
}: {
  clipName: string;
  file: File | undefined;
  disabled?: boolean;
  onChange: (file: File | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => (file ? onChange(null) : inputRef.current?.click())}
        title={file ? `${clipName} uploaded — click to remove` : `Upload ${clipName}`}
        className={cn(
          "mt-1 flex w-full items-center gap-1.5 rounded-md border px-2 py-1 text-left text-[11px] transition-colors",
          file
            ? "border-emerald-500/50 text-emerald-400"
            : "border-dashed text-muted-foreground hover:border-foreground/40 hover:text-foreground",
        )}
      >
        {file ? <CheckIcon className="size-3 shrink-0" /> : <UploadIcon className="size-3 shrink-0" />}
        <span className="truncate">{clipName}</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/webm"
        className="hidden"
        onChange={(event) => {
          onChange(event.target.files?.[0] ?? null);
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
    </>
  );
}
