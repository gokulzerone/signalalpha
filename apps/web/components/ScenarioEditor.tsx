"use client";
import { useState } from "react";
import type { Valuation } from "@/lib/api";
import { fmt } from "@/lib/format";

// Client-side recomputation with the same steps the backend serves in `spec` (PRD §12.2.7).
type Params = { revenue_growth: number; ebitda_margin: number; exit_ev_ebitda: number; horizon_years: number };

function compute(inputs: Record<string, number | null>, p: Params) {
  const ttm_revenue = inputs.ttm_revenue ?? 0, net_debt = inputs.net_debt ?? 0, shares = inputs.shares_outstanding_cr ?? 1, price = inputs.price ?? 1;
  const forward_revenue = ttm_revenue * Math.pow(1 + p.revenue_growth, p.horizon_years);
  const forward_ebitda = forward_revenue * p.ebitda_margin;
  const enterprise_value = forward_ebitda * p.exit_ev_ebitda;
  const equity_value = enterprise_value - net_debt;
  const value_per_share = equity_value / shares;
  const implied_change_vs_price = value_per_share / price - 1;
  return { forward_revenue, forward_ebitda, enterprise_value, equity_value, value_per_share, implied_change_vs_price };
}

export function ScenarioEditor({ valuation }: { valuation: Valuation }) {
  const [params, setParams] = useState<Record<string, Params>>(
    Object.fromEntries(valuation.scenarios.map((s) => [s.name, { revenue_growth: Number(s.assumptions.revenue_growth), ebitda_margin: Number(s.assumptions.ebitda_margin), exit_ev_ebitda: Number(s.assumptions.exit_ev_ebitda), horizon_years: Number(s.assumptions.horizon_years) }])),
  );
  const fields: (keyof Params)[] = ["revenue_growth", "ebitda_margin", "exit_ev_ebitda", "horizon_years"];
  return (
    <div>
      <div className="text-muted text-[11px] mb-2">Source: {valuation.source === "agent" ? "Valuation agent parameters" : "defaults around trailing values"}. Edit any parameter; values recompute with the served formula. Research scenarios, not forecasts.</div>
      <table>
        <thead><tr><th>scenario</th>{fields.map((f) => <th key={f}>{f}</th>)}<th>fwd revenue</th><th>fwd EBITDA</th><th>EV</th><th>equity</th><th>value / share</th><th>vs price</th></tr></thead>
        <tbody>
          {valuation.scenarios.map((s) => {
            const p = params[s.name];
            const r = compute(valuation.inputs, p);
            return (
              <tr key={s.name}>
                <td className="text-slate-100">{s.name}</td>
                {fields.map((f) => (
                  <td key={f}><input type="number" step={f === "horizon_years" ? 1 : 0.01} value={p[f]} onChange={(e) => setParams({ ...params, [s.name]: { ...p, [f]: Number(e.target.value) } })} className="bg-ink-700 border border-ink-500 rounded px-1 w-20 text-slate-200" /></td>
                ))}
                <td>{fmt.num(r.forward_revenue, 1)}</td><td>{fmt.num(r.forward_ebitda, 1)}</td><td>{fmt.num(r.enterprise_value, 1)}</td><td>{fmt.num(r.equity_value, 1)}</td>
                <td className="text-slate-100">₹{fmt.num(r.value_per_share, 2)}</td>
                <td className={r.implied_change_vs_price >= 0 ? "text-pos" : "text-neg"}>{fmt.pct(r.implied_change_vs_price)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <details className="mt-2 text-[11px] text-muted"><summary>formula spec</summary><pre>{JSON.stringify(valuation.spec.steps, null, 1)}</pre></details>
    </div>
  );
}
