"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const FIELDS: { key: string; label: string; type: "number" | "text" | "select"; options?: string[] }[] = [
  { key: "since", label: "window (days)", type: "number" },
  { key: "sector", label: "sector", type: "text" },
  { key: "market_cap_min", label: "mcap min", type: "number" },
  { key: "market_cap_max", label: "mcap max", type: "number" },
  { key: "opportunity_min", label: "opp ≥", type: "number" },
  { key: "risk_max", label: "risk ≤", type: "number" },
  { key: "attention_gap_min", label: "attn ≥", type: "number" },
  { key: "signal_type", label: "signal type", type: "text" },
  { key: "exclude_illiquid", label: "liquidity floor", type: "select", options: ["", "true"] },
  { key: "surveillance", label: "surveillance", type: "select", options: ["", "true", "false"] },
];

export function Filters() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v); else next.delete(k);
    router.push(`${pathname}?${next.toString()}`);
  };
  return (
    <div className="flex flex-wrap gap-3 mb-3 text-[11px]">
      {FIELDS.map((f) => (
        <label key={f.key} className="text-muted flex items-center gap-1">
          {f.label}
          {f.type === "select" ? (
            <select value={params.get(f.key) ?? ""} onChange={(e) => set(f.key, e.target.value)} className="bg-ink-700 border border-ink-500 rounded px-1 text-slate-200">
              {f.options!.map((o) => <option key={o} value={o}>{o || "any"}</option>)}
            </select>
          ) : (
            <input type={f.type} defaultValue={params.get(f.key) ?? ""} onBlur={(e) => set(f.key, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(f.key, (e.target as HTMLInputElement).value); }} className="bg-ink-700 border border-ink-500 rounded px-1 w-24 text-slate-200" />
          )}
        </label>
      ))}
    </div>
  );
}
