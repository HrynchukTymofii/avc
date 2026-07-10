"use client";

import { Button } from "@/components/ui/button";

interface VideoPreviewProps {
  video: string;
  audio?: string;
}

export function VideoPreview({ video, audio }: VideoPreviewProps) {
  return (
    <div className="animate-fade-up space-y-3">
      <div className="overflow-hidden rounded-lg border bg-black">
        <video src={video} controls playsInline className="aspect-video w-full" />
      </div>
      {audio && (
        <div className="rounded-lg border bg-card p-3">
          <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Voiceover track
          </p>
          <audio src={audio} controls className="w-full" />
        </div>
      )}
      <div className="flex gap-2">
        <Button asChild>
          <a href={video} download>
            Download video
          </a>
        </Button>
        {audio && (
          <Button asChild variant="secondary">
            <a href={audio} download>
              Download audio
            </a>
          </Button>
        )}
      </div>
    </div>
  );
}
