import { api, type Performance } from "@/lib/api";
import { fmt } from "@/lib/format";
import { DecayChart } from "@/components/Charts";

// Every signal type with its backtest statistics, sample size and decay curve (PRD §12.3).
export default async function SignalsPage({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const { as_of } = await searchParams;
  const perf = await api<Performance>("/signals/performance", { as_of });
  const byType = new Map<string, typeof perf.data.rows>();
  for (const r of perf.data.rows) if (r.decile === 0) byType.set(r.subject, [...(byType.get(r.subject) ?? []), r]);
  return (
    <div>
      <div className="text-muted text-[11px] mb-3">backtest run {perf.data.backtest_run_id ?? "none"} · as of {fmt.date(perf.data.as_of)} · config {perf.data.config_version ?? "–"} · greyed rows have fewer than 30 events</div>
      <table><thead><tr><th>signal type</th><th>horizon</th><th>n</th><th>hit rate</th><th>mean excess</th><th>median excess</th><th>95% CI</th><th>IC</th><th>Sharpe</th><th>max DD</th><th>turnover</th><th>cost drag</th><th>decay</th></tr></thead><tbody>
        {[...byType.entries()].map(([type, rows]) => rows.sort((a, b) => a.horizon_days - b.horizon_days).map((r, i) => {
          const s = r.stats as Record<string, number | null | Record<string, number | null>>;
          const decay = Object.entries((s.decay as Record<string, number | null>) ?? {}).map(([k, v]) => ({ horizon: `${k}d`, mean_excess: v }));
          return (
            <tr key={`${type}-${r.horizon_days}`} className={r.low_sample ? "text-muted" : ""} title={r.low_sample ? "fewer than 30 events" : ""}>
              <td className="text-slate-100">{i === 0 ? type : ""}</td><td>{r.horizon_days}d</td><td>{r.n}{r.low_sample ? " ⚠" : ""}</td>
              <td>{fmt.pct(s.hit_rate as number | null)}</td><td className={(s.mean_excess as number) > 0 ? "text-pos" : "text-neg"}>{fmt.pct(s.mean_excess as number | null)}</td><td>{fmt.pct(s.median_excess as number | null)}</td>
              <td>{fmt.pct(s.ci_low as number | null)} to {fmt.pct(s.ci_high as number | null)}</td><td>{fmt.num(s.information_coefficient as number | null)}</td><td>{fmt.num(s.sharpe as number | null)}</td><td>{fmt.pct(s.max_drawdown as number | null)}</td><td>{fmt.num(s.turnover as number | null, 1)}</td><td>{fmt.pct(s.cost_drag as number | null)}</td>
              <td>{i === 0 ? <DecayChart data={decay} /> : ""}</td>
            </tr>
          );
        }))}
      </tbody></table>
    </div>
  );
}
