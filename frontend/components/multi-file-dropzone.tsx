"use client";

import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface MultiFileDropzoneProps {
  label: string;
  hint?: string;
  accept: string[]; // MIME types
  maxMb: number;
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function MultiFileDropzone({
  label,
  hint,
  accept,
  maxMb,
  files,
  onChange,
  disabled,
}: MultiFileDropzoneProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = (candidates: FileList | null) => {
    if (!candidates?.length) return;
    const next = [...files];
    for (const candidate of Array.from(candidates)) {
      if (!accept.includes(candidate.type)) {
        setError(`${candidate.name}: unsupported file type`);
        continue;
      }
      if (candidate.size > maxMb * 1024 * 1024) {
        setError(`${candidate.name}: maximum size is ${maxMb} MB`);
        continue;
      }
      // Same name replaces the earlier selection (the backend matches by name).
      const existing = next.findIndex(
        (f) => f.name.toLowerCase() === candidate.name.toLowerCase(),
      );
      if (existing >= 0) next[existing] = candidate;
      else next.push(candidate);
      setError(null);
    }
    onChange(next);
  };

  const remove = (index: number) => {
    onChange(files.filter((_, i) => i !== index));
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-1.5">
      <label
        htmlFor={inputId}
        className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
      >
        {label}
      </label>

      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={`Upload ${label}`}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!disabled && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!disabled) add(event.dataTransfer.files);
        }}
        className={cn(
          "flex min-h-20 cursor-pointer items-center justify-center rounded-lg border border-dashed transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-input hover:border-primary/50",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        <div className="px-6 py-5 text-center">
          <p className="text-sm text-muted-foreground">
            Drop files here or <span className="text-primary">browse</span>
          </p>
          {hint && (
            <p className="mt-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground/70">
              {hint}
            </p>
          )}
        </div>
      </div>

      {files.length > 0 && (
        <ul className="space-y-1">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-1.5"
            >
              <span className="truncate font-mono text-xs">{file.name}</span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                  {formatSize(file.size)}
                </span>
                {!disabled && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
                    onClick={() => remove(index)}
                  >
                    Remove
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <input
        ref={inputRef}
        id={inputId}
        type="file"
        multiple
        accept={accept.join(",")}
        className="hidden"
        disabled={disabled}
        onChange={(event) => add(event.target.files)}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
