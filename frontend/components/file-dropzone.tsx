"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = ["image/png", "image/jpeg"];
const MAX_MB = 20;

interface FileDropzoneProps {
  label: string;
  hint?: string;
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

export function FileDropzone({ label, hint, file, onChange, disabled }: FileDropzoneProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const accept = (candidate: File | undefined) => {
    if (!candidate) return;
    if (!ACCEPTED_TYPES.includes(candidate.type)) {
      setError("PNG or JPEG only");
      return;
    }
    if (candidate.size > MAX_MB * 1024 * 1024) {
      setError(`Maximum size is ${MAX_MB} MB`);
      return;
    }
    setError(null);
    onChange(candidate);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label
          htmlFor={inputId}
          className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
        >
          {label}
        </label>
        {file && !disabled && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
            onClick={() => {
              onChange(null);
              setError(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            Remove
          </Button>
        )}
      </div>

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
          if (!disabled) accept(event.dataTransfer.files[0]);
        }}
        className={cn(
          "relative flex min-h-36 cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-input hover:border-primary/50",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        {preview ? (
          // Object URLs are local blobs; next/image optimization does not apply.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={preview}
            alt={`${label} preview`}
            className="max-h-64 w-full object-contain"
          />
        ) : (
          <div className="px-6 py-8 text-center">
            <p className="text-sm text-muted-foreground">
              Drop an image here or <span className="text-primary">browse</span>
            </p>
            {hint && (
              <p className="mt-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground/70">
                {hint}
              </p>
            )}
          </div>
        )}
      </div>

      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        className="hidden"
        disabled={disabled}
        onChange={(event) => accept(event.target.files?.[0])}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
