"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { JobProgress } from "@/components/job-progress";
import { MultiFileDropzone } from "@/components/multi-file-dropzone";
import { RecentJobs } from "@/components/recent-jobs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { deleteLora, getLoras, submitLoraTraining } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { isTerminal, useJobPolling } from "@/lib/use-job-polling";
import type { LoraStyle } from "@/types/api";

const STEP_PRESETS = [
  { value: "1000", label: "Fast · 1000 steps (~1 h)" },
  { value: "2000", label: "Standard · 2000 steps (~1–2 h)" },
  { value: "3000", label: "Thorough · 3000 steps (~2–3 h)" },
] as const;

const TRIGGER_RE = /^[A-Za-z0-9_]{2,30}$/;

export default function LoraPage() {
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<string>("2000");
  const [images, setImages] = useState<File[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [styles, setStyles] = useState<LoraStyle[] | null>(null);

  const status = useJobPolling(jobId);
  const busy = submitting || (jobId !== null && !isTerminal(status));

  const refreshStyles = useCallback(async () => {
    try {
      setStyles((await getLoras()).loras);
    } catch {
      setStyles([]);
    }
  }, []);

  useEffect(() => {
    void refreshStyles();
  }, [refreshStyles]);

  const terminalNotified = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && isTerminal(status) && terminalNotified.current !== jobId) {
      terminalNotified.current = jobId;
      setRefreshKey((key) => key + 1);
      void refreshStyles();
    }
  }, [jobId, status, refreshStyles]);

  const triggerInvalid = trigger.length > 0 && !TRIGGER_RE.test(trigger);
  const canSubmit =
    name.trim().length > 0 && TRIGGER_RE.test(trigger) && images.length >= 5;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitLoraTraining({
        name: name.trim(),
        trigger,
        images,
        description: description.trim() || undefined,
        steps: Number(steps),
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
    setName("");
    setTrigger("");
    setDescription("");
    setImages([]);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteLora(id);
      await refreshStyles();
    } catch {
      // list refresh will show the truth either way
      await refreshStyles();
    }
  };

  return (
    <div className="space-y-10">
      <header className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight">Style Lab</h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Train a reusable style from your own images — a character, a drawing style,
          a brand look. Upload 20–50 varied images, pick a made-up trigger word, and
          after training (1–2 hours) the style appears in the Image and B-roll
          generators.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[5fr_4fr]">
        <div
          className="animate-fade-up space-y-5"
          style={{ "--delay": "0.08s" } as React.CSSProperties}
        >
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label
                htmlFor="style-name"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Style name
              </label>
              <Input
                id="style-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Ink Sketch Character"
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor="trigger"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Trigger word
              </label>
              <Input
                id="trigger"
                value={trigger}
                onChange={(event) => setTrigger(event.target.value.trim())}
                placeholder="zorblatt_style"
                disabled={busy}
              />
              <p
                className={
                  triggerInvalid ? "text-xs text-destructive" : "text-xs text-muted-foreground/80"
                }
              >
                A made-up word (letters, digits, underscores) that will summon this
                style in prompts.
              </p>
            </div>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label
                htmlFor="description"
                className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
              >
                Style description (optional)
              </label>
              <Input
                id="description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="flat pastel cartoon, thick outlines"
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Training length
              </label>
              <Select
                value={steps}
                onValueChange={(value) => {
                  if (value !== null) setSteps(value);
                }}
                disabled={busy}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STEP_PRESETS.map((preset) => (
                    <SelectItem key={preset.value} value={preset.value}>
                      {preset.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <MultiFileDropzone
            label="Training images"
            hint="20–50 varied images · PNG or JPEG · max 20 MB each"
            accept={["image/png", "image/jpeg"]}
            maxMb={20}
            files={images}
            onChange={setImages}
            disabled={busy}
          />
          {images.length > 0 && images.length < 5 && (
            <p className="text-xs text-muted-foreground">
              {images.length} of at least 5 images selected.
            </p>
          )}

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
            {busy ? "Training…" : "Start training"}
          </Button>
          <p className="text-center font-mono text-[11px] uppercase tracking-wider text-muted-foreground/70">
            Training blocks the GPU queue for its whole run — start it when you are
            done generating.
          </p>
        </div>

        <div
          className="animate-fade-up space-y-4"
          style={{ "--delay": "0.16s" } as React.CSSProperties}
        >
          <JobProgress status={status} />
          {status?.status === "finished" && (
            <div className="space-y-4 rounded-lg border bg-card p-5">
              <p className="font-mono text-xs uppercase tracking-widest text-primary">
                Style ready
              </p>
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{name || "Your style"}</span>{" "}
                is trained. Pick it in the Style dropdown on the Image or B-roll page —
                the trigger word is added to your prompts automatically.
              </p>
              <Button variant="secondary" onClick={reset} className="w-full">
                Train another style
              </Button>
            </div>
          )}
          {!status && !busy && (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Training progress will appear here.
            </div>
          )}

          <section className="space-y-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Trained styles
            </h2>
            {styles === null ? null : styles.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing trained yet — your finished styles will be listed here.
              </p>
            ) : (
              <ul className="space-y-2">
                {styles.map((style) => (
                  <li
                    key={style.id}
                    className="flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm">{style.name}</p>
                      <p className="font-mono text-[11px] text-muted-foreground">
                        {style.trigger} · {timeAgo(style.createdAt)}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 shrink-0 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
                      onClick={() => handleDelete(style.id)}
                    >
                      Delete
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      <RecentJobs kind="lora_training" refreshKey={refreshKey} />
    </div>
  );
}
