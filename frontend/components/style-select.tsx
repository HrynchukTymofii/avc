"use client";

import { PaletteIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getLoras } from "@/lib/api";
import type { LoraStyle } from "@/types/api";

const NONE = "__none__";

// Allowed lora_scale presets (backend accepts 0.1–2.0; 1.0 = as trained).
const SCALES = ["0.6", "0.8", "1.0", "1.2", "1.5", "2.0"] as const;

interface StyleScaleSelectProps {
  value: string; // one of SCALES
  onChange: (scale: string) => void;
  disabled?: boolean;
}

/** Strength of the applied style (lora_scale). Higher pushes the trained look
 * harder against the prompt; useful when a style barely shows at 1.0. */
export function StyleScaleSelect({ value, onChange, disabled }: StyleScaleSelectProps) {
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (next !== null) onChange(next);
      }}
      disabled={disabled}
      items={Object.fromEntries(SCALES.map((scale) => [scale, `Style ×${scale}`]))}
    >
      <SelectTrigger size="sm" className="max-w-32">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SCALES.map((scale) => (
          <SelectItem key={scale} value={scale}>
            Style ×{scale}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

interface StyleSelectProps {
  value: string; // lora id, "" = no style
  onChange: (id: string) => void;
  disabled?: boolean;
  /** Bare small select for the composer bar — no label, no caption. */
  compact?: boolean;
  /** Bigger composer button with a visual tile for the chosen style. */
  tile?: boolean;
}

/** Trained style (LoRA) picker fed by /api/loras. Styles apply to the Wan2.2 5B
 * engine only — the backend rejects other models, and the trigger word is added
 * to the prompt automatically. */
export function StyleSelect({ value, onChange, disabled, compact, tile }: StyleSelectProps) {
  const [styles, setStyles] = useState<LoraStyle[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLoras()
      .then((response) => {
        if (!cancelled) setStyles(response.loras);
      })
      .catch(() => setStyles([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = styles?.find((style) => style.id === value);

  const select = (
    <Select
      value={value || NONE}
      onValueChange={(next) => {
        if (next !== null) onChange(next === NONE ? "" : next);
      }}
      disabled={disabled || styles === null}
      items={{
        [NONE]: "No style",
        ...Object.fromEntries((styles ?? []).map((style) => [style.id, style.name])),
      }}
    >
      <SelectTrigger
        size={compact ? "sm" : "default"}
        className={
          tile
            ? "h-12 max-w-52 gap-2 rounded-lg pl-1.5"
            : compact
              ? "max-w-44"
              : "w-full"
        }
      >
        {tile && (
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-md bg-linear-to-br from-primary/80 to-[oklch(0.55_0.22_310)] font-heading text-sm font-bold text-white"
          >
            {selected ? (
              selected.name.charAt(0).toUpperCase()
            ) : (
              <PaletteIcon className="size-4" />
            )}
          </span>
        )}
        <SelectValue placeholder={styles === null ? "Loading styles…" : undefined} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>No style</SelectItem>
        {styles?.map((style) => (
          <SelectItem key={style.id} value={style.id}>
            {style.name}
            <span className="ml-2 font-mono text-[10px] uppercase text-muted-foreground">
              {style.trigger}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  if (compact || tile) return select;

  return (
    <div className="space-y-1.5">
      <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Style
      </label>
      {select}
      {selected ? (
        <p className="text-xs text-muted-foreground/80">
          Trigger word <span className="font-mono">{selected.trigger}</span> is added to
          your prompt automatically.
        </p>
      ) : (
        styles !== null &&
        styles.length === 0 && (
          <p className="text-xs text-muted-foreground/80">
            No trained styles yet —{" "}
            <Link href="/lora" className="text-primary underline-offset-2 hover:underline">
              train one in the Style Lab
            </Link>
            .
          </p>
        )
      )}
    </div>
  );
}
