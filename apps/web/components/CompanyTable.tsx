"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import type { CompanyRow } from "@/lib/api";
import { fmt } from "@/lib/format";
import { ScoreCell } from "./ScoreCell";

type Col = { key: string; label: string; get: (r: CompanyRow) => number | string | null };
const COLS: Col[] = [
  { key: "name", label: "Company", get: (r) => r.name },
  { key: "sector", label: "Sector", get: (r) => r.sector },
  { key: "market_cap_cr", label: "Mcap ₹cr", get: (r) => r.market_cap_cr },
  { key: "opportunity", label: "Opp", get: (r) => r.scores.opportunity },
  { key: "attention_gap", label: "Attn gap", get: (r) => r.scores.attention_gap },
  { key: "risk", label: "Risk", get: (r) => r.scores.risk },
  { key: "key_change", label: "Key change", get: (r) => r.key_change },
  { key: "strongest_positive", label: "Strongest +", get: (r) => r.strongest_positive },
  { key: "strongest_negative", label: "Strongest −", get: (r) => r.strongest_negative },
  { key: "data_quality_failures", label: "DQ", get: (r) => r.data_quality_failures },
];

// One line per cell: the first sentence, clipped (PRD §12.1 "key change (one line)").
const oneLine = (text: string): string => {
  const first = text.split(/(?<=\.)\s/)[0];
  return first.length > 110 ? `${first.slice(0, 107)}…` : first;
};

export function CompanyTable({ rows, defaultSort = "opportunity" }: { rows: CompanyRow[]; defaultSort?: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const asOf = params.get("as_of") ?? undefined;
  const [sort, setSort] = useState<{ key: string; desc: boolean }>({ key: defaultSort, desc: true });
  const sorted = useMemo(() => {
    const col = COLS.find((c) => c.key === sort.key) ?? COLS[0];
    return [...rows].sort((a, b) => {
      const va = col.get(a), vb = col.get(b);
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.desc ? -cmp : cmp;
    });
  }, [rows, sort]);
  const href = (id: number) => `/companies/${id}${asOf ? `?as_of=${asOf}` : ""}`;
  return (
    <table>
      <thead>
        <tr>
          {COLS.map((c) => (
            <th key={c.key} className="cursor-pointer select-none" onClick={() => setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : true })}>
              {c.label}{sort.key === c.key ? (sort.desc ? " ▾" : " ▴") : ""}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={r.id} data-href={href(r.id)} className="cursor-pointer hover:bg-ink-700" onClick={() => router.push(href(r.id))}>
            <td>
              <div className="text-slate-100">{r.name}</div>
              <div className="text-muted text-[11px]">{r.ticker}{r.is_illiquid ? " · illiquid" : ""}{r.gsm_stage || r.asm_stage ? " · surveillance" : ""}</div>
            </td>
            <td>{r.sector}</td>
            <td>{fmt.num(r.market_cap_cr, 0)}</td>
            <td><ScoreCell companyId={r.id} scoreType="opportunity" value={r.scores.opportunity} asOf={asOf} /></td>
            <td><ScoreCell companyId={r.id} scoreType="attention_gap" value={r.scores.attention_gap} asOf={asOf} /></td>
            <td><ScoreCell companyId={r.id} scoreType="risk" value={r.scores.risk} asOf={asOf} /></td>
            <td className="max-w-xs text-[12px] truncate" title={r.key_change ?? ""}>{r.key_change ? oneLine(r.key_change) : <span className="text-muted">no thesis yet</span>}</td>
            <td className="max-w-[14rem] text-pos text-[12px] truncate" title={r.strongest_positive ?? ""}>{r.strongest_positive ? oneLine(r.strongest_positive) : "–"}</td>
            <td className="max-w-[14rem] text-neg text-[12px] truncate" title={r.strongest_negative ?? ""}>{r.strongest_negative ? oneLine(r.strongest_negative) : "–"}</td>
            <td className={r.data_quality_failures ? "text-warn" : "text-muted"}>{r.data_quality_failures ? `${r.data_quality_failures} failures` : "ok"}</td>
          </tr>
        ))}
        {sorted.length === 0 && <tr><td colSpan={COLS.length} className="text-muted">Nothing in this window.</td></tr>}
      </tbody>
    </table>
  );
}
