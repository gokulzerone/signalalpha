"use client";
import { useState } from "react";
import type { Component, ScoreOut } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";

// A score value that reveals its component breakdown on hover (PRD §12.1, §2.7).
export function ScoreCell({ companyId, scoreType, value, asOf }: { companyId: number; scoreType: string; value: number | null; asOf?: string }) {
  const [rows, setRows] = useState<Record<string, Component> | null>(null);
  const [open, setOpen] = useState(false);
  const load = async () => {
    setOpen(true);
    if (rows) return;
    const q = asOf ? `?as_of=${asOf}` : "";
    const res = await fetch(`/api/companies/${companyId}/scores${q}`);
    if (!res.ok) return;
    const body = (await res.json()) as { data: ScoreOut[] };
    const s = body.data.find((x) => x.score_type === scoreType);
    setRows(s?.components.components ?? {});
  };
  return (
    <span className="relative" onMouseEnter={load} onMouseLeave={() => setOpen(false)}>
      <span className={scoreTone(scoreType, value)}>{fmt.score(value)}</span>
      {open && rows && (
        <div className="absolute z-20 left-0 top-5 card w-80 text-[11px] shadow-xl">
          <div className="text-muted mb-1">{scoreType} components</div>
          <table>
            <thead><tr><th>component</th><th>raw</th><th>pct</th><th>w</th></tr></thead>
            <tbody>
              {Object.entries(rows).map(([k, c]) => (
                <tr key={k}><td>{k}</td><td>{fmt.num(c.raw, 3)}</td><td>{fmt.score(c.percentile)}</td><td>{c.weight}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </span>
  );
}
