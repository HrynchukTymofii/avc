"use client";

import { useEffect, useState } from "react";
import {
  DownloadIcon,
  RefreshCwIcon,
  Trash2Icon,
  Wand2Icon,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { deleteJob, getJobDetail, regenerateJob, submitUpscale } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { JobDetail, JobKind } from "@/types/api";

const KIND_LABELS: Record<JobKind, string> = {
  talking_head: "Talking head",
  broll: "B-roll",
  image: "Image",
  full_video: "Full video",
  lora_training: "Style training",
  upscale: "Upscale",
};

interface JobDetailDialogProps {
  jobId: string | null;
  onClose: () => void;
  /** Called after an action changed the library (regenerate, upscale, delete). */
  onChanged?: () => void;
}

export function JobDetailDialog({ jobId, onClose, onChanged }: JobDetailDialogProps) {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [busy, setBusy] = useState<"regenerate" | "upscale" | "delete" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    setDetail(null);
    setLoadError(null);
    setImageIndex(0);
    setBusy(null);
    setActionError(null);
    setNotice(null);
    setConfirmingDelete(false);
    if (!jobId) return;
    getJobDetail(jobId)
      .then(setDetail)
      .catch((error) =>
        setLoadError(error instanceof Error ? error.message : "Could not load the job"),
      );
  }, [jobId]);

  const images = detail?.images ?? (detail?.image ? [detail.image] : []);
  const selectedImage = images[imageIndex] ?? images[0];
  const downloadUrl = detail?.video ?? selectedImage ?? detail?.audio;

  const run = async (
    action: "regenerate" | "upscale" | "delete",
    work: () => Promise<void>,
  ) => {
    setBusy(action);
    setActionError(null);
    setNotice(null);
    try {
      await work();
      onChanged?.();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  const handleRegenerate = () =>
    run("regenerate", async () => {
      if (!detail) return;
      await regenerateJob(detail.jobId);
      setNotice("Re-queued with the same settings — it will appear as a new job.");
    });

  const handleUpscale = () =>
    run("upscale", async () => {
      if (!detail) return;
      const source =
        detail.video || images.length <= 1
          ? undefined
          : imageIndex === 0
            ? "image"
            : `image_${imageIndex + 1}`;
      await submitUpscale({ sourceJob: detail.jobId, source });
      setNotice("Sent to the upscaler — it will appear as a new upscale job.");
    });

  const handleDelete = () => {
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    void run("delete", async () => {
      if (!detail) return;
      await deleteJob(detail.jobId);
      onClose();
    });
  };

  return (
    <Dialog open={jobId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {loadError && (
          <Alert variant="destructive">
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        )}
        {!detail && !loadError && (
          <div className="space-y-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="aspect-video w-full rounded-xl" />
          </div>
        )}
        {detail && (
          <div className="space-y-4">
            <div className="pr-8">
              <DialogTitle className="truncate">{detail.label || "Untitled"}</DialogTitle>
              <p className="mt-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                {KIND_LABELS[detail.kind]} · {formatDateTime(detail.createdAt)} (
                {timeAgo(detail.createdAt)})
              </p>
            </div>

            {/* media */}
            {detail.video ? (
              <video
                src={detail.video}
                controls
                playsInline
                className="max-h-[50vh] w-full rounded-xl bg-black"
              />
            ) : images.length > 0 ? (
              <div className="space-y-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={selectedImage}
                  alt={detail.label || "generated image"}
                  className="max-h-[50vh] w-full rounded-xl bg-black object-contain"
                />
                {images.length > 1 && (
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {images.map((url, index) => (
                      <button
                        key={url}
                        type="button"
                        onClick={() => setImageIndex(index)}
                        className={
                          index === imageIndex
                            ? "shrink-0 rounded-lg ring-2 ring-primary"
                            : "shrink-0 rounded-lg opacity-60 transition-opacity hover:opacity-100"
                        }
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={url}
                          alt={`variation ${index + 1}`}
                          className="h-16 w-24 rounded-lg object-cover"
                        />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : detail.audio ? (
              <audio src={detail.audio} controls className="w-full" />
            ) : detail.status === "failed" ? null : (
              <div className="rounded-xl border border-dashed p-6 text-center font-mono text-xs uppercase tracking-widest text-muted-foreground">
                {detail.status}
              </div>
            )}

            {detail.error && (
              <Alert variant="destructive">
                <AlertDescription>{detail.error}</AlertDescription>
              </Alert>
            )}

            {/* prompt / script */}
            {detail.prompt && (
              <div className="rounded-xl bg-secondary/50 p-3">
                <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Prompt
                </p>
                <p className="max-h-32 overflow-y-auto whitespace-pre-wrap text-sm text-foreground/90">
                  {detail.prompt}
                </p>
              </div>
            )}

            {/* meta */}
            <div className="flex flex-wrap items-center gap-2">
              {detail.model && <Badge variant="secondary">{detail.model}</Badge>}
              {detail.voice && <Badge variant="secondary">voice · {detail.voice}</Badge>}
              <Badge variant="secondary">
                {detail.cost > 0 ? `${detail.cost} credits` : "free"}
              </Badge>
              {detail.status === "failed" && <Badge variant="destructive">failed</Badge>}
            </div>

            {actionError && (
              <Alert variant="destructive">
                <AlertDescription>{actionError}</AlertDescription>
              </Alert>
            )}
            {notice && (
              <Alert>
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}

            {/* actions */}
            <div className="flex flex-wrap items-center gap-2 border-t pt-4">
              <Button
                size="sm"
                onClick={handleRegenerate}
                disabled={busy !== null || !detail.canRegenerate}
                title={
                  detail.canRegenerate
                    ? "Run this job again with the same settings"
                    : "This job's settings weren't saved, so it can't be regenerated"
                }
              >
                <RefreshCwIcon className="size-3.5" />
                {busy === "regenerate" ? "Queueing…" : "Regenerate"}
              </Button>
              {detail.canUpscale && detail.kind !== "upscale" && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleUpscale}
                  disabled={busy !== null}
                  title="Upscale this output with Real-ESRGAN — no re-upload needed"
                >
                  <Wand2Icon className="size-3.5" />
                  {busy === "upscale" ? "Queueing…" : "Upscale"}
                </Button>
              )}
              {downloadUrl && (
                <Button size="sm" variant="secondary" render={<a href={downloadUrl} download />}>
                  <DownloadIcon className="size-3.5" />
                  Download
                </Button>
              )}
              <Button
                size="sm"
                variant={confirmingDelete ? "destructive" : "ghost"}
                onClick={handleDelete}
                disabled={busy !== null}
                className="ml-auto"
              >
                <Trash2Icon className="size-3.5" />
                {busy === "delete"
                  ? "Deleting…"
                  : confirmingDelete
                    ? "Really delete?"
                    : "Delete"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
