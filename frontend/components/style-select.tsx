"use client";

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

interface StyleSelectProps {
  value: string; // lora id, "" = no style
  onChange: (id: string) => void;
  disabled?: boolean;
  /** Bare small select for the composer bar — no label, no caption. */
  compact?: boolean;
}

/** Trained style (LoRA) picker fed by /api/loras. Styles apply to the Wan2.2 5B
 * engine only — the backend rejects other models, and the trigger word is added
 * to the prompt automatically. */
export function StyleSelect({ value, onChange, disabled, compact }: StyleSelectProps) {
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
        className={compact ? "max-w-44" : "w-full"}
      >
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

  if (compact) return select;

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
