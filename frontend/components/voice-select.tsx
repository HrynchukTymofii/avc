"use client";

import { useEffect, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getVoices } from "@/lib/api";
import type { Voice } from "@/types/api";

interface VoiceSelectProps {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  /** Bare small select for the composer bar — no label, no caption. */
  compact?: boolean;
}

/** Voice picker fed by /api/voices; auto-selects the first voice. */
export function VoiceSelect({ value, onChange, disabled, compact }: VoiceSelectProps) {
  const [voices, setVoices] = useState<Voice[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVoices()
      .then((response) => {
        if (cancelled) return;
        setVoices(response.voices);
        if (response.voices.length > 0) onChange(response.voices[0].id);
      })
      .catch(() => setVoices([]));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = (
    <Select
      value={value}
      onValueChange={(next) => {
        if (next !== null) onChange(next);
      }}
      disabled={disabled || !voices?.length}
      items={Object.fromEntries((voices ?? []).map((item) => [item.id, item.name]))}
    >
      <SelectTrigger size={compact ? "sm" : "default"} className={compact ? "max-w-44" : "w-full"}>
        <SelectValue
          placeholder={voices === null ? "Loading voices…" : "No voices available"}
        />
      </SelectTrigger>
      <SelectContent>
        {voices?.map((item) => (
          <SelectItem key={item.id} value={item.id}>
            {item.name}
            <span className="ml-2 font-mono text-[10px] uppercase text-muted-foreground">
              {item.language}
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
        Voice
      </label>
      {select}
      {voices?.length === 0 && (
        <p className="text-xs text-destructive">
          No voices configured — add reference clips on the server
          (backend/assets/voices).
        </p>
      )}
    </div>
  );
}
