"use client";

import { XIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Full-height studio page: the generation feed grows from the top and the
 * composer stays pinned to the bottom of the viewport (Higgsfield-style). */
export function Studio({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[calc(100dvh-7.5rem)] flex-col">{children}</div>;
}

/** The fixed input bar. Sticks to the bottom while the feed scrolls behind a
 * soft fade so cards never collide with it visually. */
export function StudioComposer({ children }: { children: React.ReactNode }) {
  return (
    <div className="sticky bottom-0 z-30 -mx-4 mt-auto bg-linear-to-t from-background via-background/85 to-transparent px-4 pb-4 pt-8">
      <div className="mx-auto w-full max-w-4xl rounded-3xl border bg-popover/80 p-3 shadow-2xl shadow-black/40 backdrop-blur-xl">
        {children}
      </div>
    </div>
  );
}

/** One compact control in the composer's bottom row. */
export function ComposerControl({
  label,
  children,
  className,
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {label && (
        <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      )}
      {children}
    </div>
  );
}

/** Floating side panel for the advanced options (voice, uploads, …). */
export function AdvancedPanel({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <aside className="fixed bottom-28 right-4 z-40 w-[min(22rem,calc(100vw-2rem))] animate-fade-up">
      <div className="max-h-[65vh] overflow-y-auto rounded-3xl border bg-popover/90 p-5 shadow-2xl shadow-black/50 backdrop-blur-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <XIcon className="size-4" />
          </button>
        </div>
        <div className="space-y-5">{children}</div>
      </div>
    </aside>
  );
}
