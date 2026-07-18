"use client";

import { useSearchParams } from "next/navigation";
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
  /** Bare small select for the composer bar — no label, no cost caption. */
  compact?: boolean;
}

/** Engine picker fed by /api/models. Preselects ?model= from the URL (used by
 * the nav dropdowns) or the catalog default. Premium engines render disabled
 * until the premium tier exists. */
export function ModelSelect({ kind, value, onChange, disabled, compact }: ModelSelectProps) {
  const [engines, setEngines] = useState<EngineInfo[] | null>(null);
  // useSearchParams (not window.location) so nav clicks like /image?model=flux
  // apply even when the page is already mounted (same route, new query).
  const requested = useSearchParams().get("model");

  useEffect(() => {
    let cancelled = false;
    getModels()
      .then((response) => {
        if (!cancelled) setEngines(response.models[kind] ?? []);
      })
      .catch(() => setEngines([]));
    return () => {
      cancelled = true;
    };
  }, [kind]);

  useEffect(() => {
    if (!engines) return;
    const preselect =
      engines.find((engine) => engine.id === requested && engine.available) ??
      engines.find((engine) => engine.default) ??
      engines.find((engine) => engine.available);
    if (preselect) onChange(preselect.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engines, requested]);

  const selected = engines?.find((engine) => engine.id === value);

  const select = (
    <Select
      value={value}
      onValueChange={(next) => {
        if (next !== null) onChange(next);
      }}
      disabled={disabled || !engines?.length}
      // lets <SelectValue> render the engine label instead of the raw id
      items={Object.fromEntries((engines ?? []).map((engine) => [engine.id, engine.label]))}
    >
      <SelectTrigger size={compact ? "sm" : "default"} className={compact ? "max-w-52" : "w-full"}>
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
  );

  if (compact) return select;

  return (
    <div className="space-y-1.5">
      <label className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Model
      </label>
      {select}
      {selected && (
        <p className="text-xs text-muted-foreground/80">Cost: {selected.credits} credits</p>
      )}
    </div>
  );
}
