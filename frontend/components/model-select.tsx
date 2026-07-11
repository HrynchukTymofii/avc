"use client";

import { useEffect, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getModels } from "@/lib/api";
import type { EngineInfo, JobKind } from "@/types/api";

interface ModelSelectProps {
  kind: JobKind;
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}

/** Engine picker fed by /api/models. Preselects ?model= from the URL (used by
 * the nav dropdowns) or the catalog default. Premium engines render disabled
 * until the premium tier exists. */
export function ModelSelect({ kind, value, onChange, disabled }: ModelSelectProps) {
  const [engines, setEngines] = useState<EngineInfo[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getModels()
      .then((response) => {
        if (cancelled) return;
        const list = response.models[kind] ?? [];
        setEngines(list);
        const requested = new URLSearchParams(window.location.search).get("model");
        const preselect =
          list.find((engine) => engine.id === requested && engine.available) ??
          list.find((engine) => engine.default) ??
          list.find((engine) => engine.available);
        if (preselect) onChange(preselect.id);
      })
      .catch(() => setEngines([]));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const selected = engines?.find((engine) => engine.id === value);

  return (
    <div className="space-y-1.5">
      <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Model
      </label>
      <Select
        value={value}
        onValueChange={(next) => {
          if (next !== null) onChange(next);
        }}
        disabled={disabled || !engines?.length}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder={engines === null ? "Loading models…" : "No models"} />
        </SelectTrigger>
        <SelectContent>
          {engines?.map((engine) => (
            <SelectItem key={engine.id} value={engine.id} disabled={!engine.available}>
              {engine.label}
              <span className="ml-2 font-mono text-[10px] uppercase text-muted-foreground">
                {engine.available ? `${engine.credits} cr` : "premium · soon"}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {selected && (
        <p className="text-xs text-muted-foreground/80">Cost: {selected.credits} credits</p>
      )}
    </div>
  );
}
