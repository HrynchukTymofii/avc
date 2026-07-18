"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** Full-height studio page: the generation grid grows from the top and the
 * composer stays pinned to the bottom of the viewport (Higgsfield-style). */
export function Studio({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[calc(100dvh-7.5rem)] flex-col">{children}</div>;
}

/** The fixed input bar. Sticks to the bottom while the feed scrolls behind a
 * soft fade so tiles never collide with it visually. */
export function StudioComposer({ children }: { children: React.ReactNode }) {
  return (
    <div className="sticky bottom-0 z-30 -mx-4 mt-auto bg-linear-to-t from-background via-background/85 to-transparent px-4 pb-4 pt-8">
      <div className="mx-auto w-full max-w-4xl rounded-xl border bg-popover/85 p-3 shadow-2xl shadow-black/40 backdrop-blur-xl">
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

/** Higgsfield-style "+" attach button for the composer: opens the file picker
 * directly and previews the chosen image as a thumbnail. */
export function ComposerAttach({
  label,
  file,
  onChange,
  accept = "image/png,image/jpeg,image/webp",
  disabled,
}: {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
  accept?: string;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        title={file ? `${label}: ${file.name}` : label}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex size-12 items-center justify-center overflow-hidden rounded-lg border transition-colors disabled:opacity-50",
          file
            ? "border-primary/50"
            : "border-dashed text-muted-foreground hover:border-foreground/40 hover:text-foreground",
        )}
      >
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt={label} className="size-full object-cover" />
        ) : file ? (
          <span className="px-1 text-center font-mono text-[8px] uppercase leading-tight">
            {file.name.slice(0, 12)}
          </span>
        ) : (
          <PlusIcon className="size-5" />
        )}
      </button>
      {file && !disabled && (
        <button
          type="button"
          aria-label={`Remove ${label}`}
          onClick={() => {
            onChange(null);
            if (inputRef.current) inputRef.current.value = "";
          }}
          className="absolute -right-1.5 -top-1.5 flex size-4 items-center justify-center rounded-full bg-secondary text-foreground shadow hover:bg-accent"
        >
          <XIcon className="size-3" />
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
    </div>
  );
}
