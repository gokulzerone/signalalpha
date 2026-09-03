import { api, type DataQualityRow } from "@/lib/api";
import { fmt } from "@/lib/format";

// Per-source freshness, failure counts and per-company coverage gaps (PRD §12.4).
export default async function DataPage({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const { as_of } = await searchParams;
  const dq = await api<DataQualityRow[]>("/data-quality", { as_of });
  const bySource = new Map<string, DataQualityRow[]>();
  for (const r of dq.data) bySource.set(r.source, [...(bySource.get(r.source) ?? []), r]);
  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-slate-100 mb-2">Per-source freshness</h2>
        <table><thead><tr><th>source</th><th>companies</th><th>latest public</th><th>last success</th><th>fetch failures</th><th>parse failures</th></tr></thead><tbody>
          {[...bySource.entries()].map(([source, rows]) => {
            const latest = rows.map((r) => r.latest_public_at).filter(Boolean).sort().at(-1) ?? null;
            const success = rows.map((r) => r.last_success_at).filter(Boolean).sort().at(-1) ?? null;
            const fetchF = rows.reduce((a, r) => a + r.fetch_failure_count, 0), parseF = rows.reduce((a, r) => a + r.parse_failure_count, 0);
            return <tr key={source}><td className="text-slate-100">{source}</td><td>{rows.length}</td><td>{fmt.date(latest)}</td><td>{fmt.date(success)}</td><td className={fetchF ? "text-warn" : ""}>{fetchF}</td><td className={parseF ? "text-warn" : ""}>{parseF}</td></tr>;
          })}
        </tbody></table>
      </section>
      <section>
        <h2 className="text-slate-100 mb-2">Coverage gaps</h2>
        <table><thead><tr><th>company</th><th>source</th><th>latest public</th><th>failures</th><th>last error</th></tr></thead><tbody>
          {dq.data.filter((r) => r.fetch_failure_count + r.parse_failure_count > 0 || !r.latest_public_at).map((r) => <tr key={`${r.company_id}-${r.source}`}><td>{r.ticker ?? "market"}</td><td>{r.source}</td><td>{fmt.date(r.latest_public_at)}</td><td className="text-warn">{r.fetch_failure_count + r.parse_failure_count}</td><td className="text-[11px]">{r.last_error ?? ""}</td></tr>)}
          {dq.data.every((r) => r.fetch_failure_count + r.parse_failure_count === 0 && r.latest_public_at) && <tr><td colSpan={5} className="text-muted">No gaps: every tracked source has data and no failures.</td></tr>}
        </tbody></table>
      </section>
    </div>
  );
}
