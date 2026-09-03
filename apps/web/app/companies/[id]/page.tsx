import Link from "next/link";
import { Suspense } from "react";
import { api, apiOrNull, type AgentOutput, type Claim, type CompanyProfile, type Evidence, type FinancialRow, type Ownership, type PriceRow, type ScoreOut, type SignalOut, type Thesis, type Valuation } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";
import { TrajectoryChart, SeriesChart } from "@/components/Charts";
import { ScenarioEditor } from "@/components/ScenarioEditor";
import { Claims } from "@/components/Claims";

type Search = { as_of?: string };
const SCORE_ORDER = ["opportunity", "inflection", "quality", "valuation", "risk", "attention_gap"];

export default async function CompanyPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Search> }) {
  const { id } = await params;
  const { as_of } = await searchParams;
  const cid = Number(id);
  const q = { as_of };
  const [profile, financials, ownership, prices, signals, scores, valuation, thesis, research] = await Promise.all([
    api<CompanyProfile>(`/companies/${cid}`, q),
    api<FinancialRow[]>(`/companies/${cid}/financials`, { ...q, periods: 12, period_months: 3 }),
    api<Ownership>(`/companies/${cid}/ownership`, q),
    api<PriceRow[]>(`/companies/${cid}/prices`, q),
    api<SignalOut[]>(`/companies/${cid}/signals`, q),
    api<ScoreOut[]>(`/companies/${cid}/scores`, q),
    apiOrNull<Valuation>(`/companies/${cid}/valuation`, q),
    api<Thesis>(`/companies/${cid}/thesis`, q),
    api<Record<string, AgentOutput | null>>(`/companies/${cid}/research`, q),
  ]);
  const p = profile.data;
  const evidenceMap = new Map<number, Evidence>(thesis.data.evidence.map((e) => [e.id, e]));
  const claimEvidenceIds = new Set<number>();
  for (const a of Object.values(research.data)) for (const c of ((a?.output?.claims as Claim[] | undefined) ?? [])) c.evidence_ids.forEach((e) => claimEvidenceIds.add(e));
  for (const f of ((research.data.forensic?.output?.flags as { claims: Claim[] }[] | undefined) ?? [])) for (const c of f.claims) c.evidence_ids.forEach((e) => claimEvidenceIds.add(e));
  const missing = [...claimEvidenceIds].filter((e) => !evidenceMap.has(e));
  if (missing.length) {
    const extra = await api<Evidence[]>(`/companies/${cid}/evidence`, { ...q, ids: missing.join(",") }).catch(() => null);
    extra?.data.forEach((e) => evidenceMap.set(e.id, e));
  }
  const quarters = [...financials.data].reverse();
  const trajectory = quarters.map((r) => ({ period: r.period_end.slice(0, 7), revenue: Number(r.values.revenue), ebitda: Number(r.values.ebitda), margin: r.ratios.ebitda_margin ?? null }));
  const holdingSeries = [...ownership.data.shareholdings].reverse().map((h) => ({ x: h.period_end.slice(0, 7), promoter: Number(h.promoter_pct), pledged: Number(h.promoter_pledged_pct), institutions: Number(h.fii_pct) + Number(h.dii_pct) }));
  const business = research.data.business?.output as { orders?: { document_id: number; quote: string; value_cr: number; execution_months: number | null; evidence_id: number }[]; order_book_estimate_cr?: number; capacity_story?: string } | undefined;
  const forensic = research.data.forensic?.output as { flags?: { signal_type: string; severity: string; mechanism: string; claims: Claim[] }[] } | undefined;
  const th = thesis.data.thesis?.output as Record<string, string | Claim[]> | undefined;
  const co = thesis.data.contradiction?.output as { case_against: string; disputed_claims: { agent: string; claim: string; dispute: string; resolving_evidence: string }[]; thesis_survives: string; claims: Claim[] } | undefined;
  const docHref = (docId: number, eid?: number) => `/companies/${cid}/documents/${docId}?${eid ? `highlight=${eid}&` : ""}${as_of ? `as_of=${as_of}` : ""}`;
  const ratingHistory = signals.data.filter((s) => s.signal_type.startsWith("credit_rating"));

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <section className="flex flex-wrap gap-6 items-baseline">
        <div><div className="text-xl text-slate-100">{p.name}</div><div className="text-muted">{p.ticker} · {p.sector} · {p.industry} · {p.exchange}</div></div>
        <div>price <span className="text-slate-100">₹{fmt.num(p.price)}</span> <span className="text-muted">({fmt.date(p.price_date)})</span></div>
        <div>mcap <span className="text-slate-100">{fmt.cr(p.market_cap_cr)}</span></div>
        <div>liquidity <span className={p.is_illiquid ? "text-warn" : "text-slate-100"}>{p.is_illiquid ? "below floor" : "ok"}</span> <span className="text-muted">median ₹{fmt.num(p.median_traded_value_30d, 0)}/day</span></div>
        <div>surveillance <span className={p.gsm_stage || p.asm_stage ? "text-neg" : "text-muted"}>{p.gsm_stage ? `GSM ${p.gsm_stage}` : p.asm_stage ? `ASM ${p.asm_stage}` : "none"}</span></div>
        <div>status <span className={p.listing_status === "listed" ? "text-slate-100" : "text-neg"}>{p.listing_status}</span></div>
        <div>data quality <span className={p.data_quality_failures ? "text-warn" : "text-pos"}>{p.data_quality_failures ? `${p.data_quality_failures} failures` : "complete"}</span> <span className="text-muted">latest {fmt.date(profile.data_quality?.latest_public_at)}</span></div>
        <div className="text-muted text-[11px]">as of {profile.as_of.slice(0, 10)}</div>
      </section>

      {/* 2. Scores strip */}
      <section className="grid grid-cols-6 gap-2">
        {SCORE_ORDER.map((t) => {
          const s = scores.data.find((x) => x.score_type === t);
          return (
            <details key={t} className="card">
              <summary className="cursor-pointer"><span className="text-muted text-[11px] uppercase">{t.replace("_", " ")}</span> <span className={`text-lg ${scoreTone(t, s?.value ?? null)}`}>{fmt.score(s?.value ?? null)}</span></summary>
              {s && (
                <table className="mt-2 text-[11px]"><thead><tr><th>component</th><th>raw</th><th>pct</th><th>w</th><th>contrib</th></tr></thead><tbody>
                  {Object.entries(s.components.components).map(([k, c]) => <tr key={k}><td>{k}</td><td>{fmt.num(c.raw, 3)}</td><td>{fmt.score(c.percentile)}</td><td>{c.weight}</td><td>{fmt.num(c.contribution, 1)}</td></tr>)}
                </tbody></table>
              )}
              {s && <div className="text-muted text-[10px] mt-1">config {s.config_version} · {s.signal_ids.length} signals</div>}
            </details>
          );
        })}
      </section>

      {/* 3. Financial trajectory */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Financial trajectory</h2>
        <TrajectoryChart data={trajectory} />
        <div className="overflow-x-auto mt-3">
          <table><thead><tr><th>quarter</th><th>revenue</th><th>EBITDA</th><th>margin</th><th>rev YoY</th><th>PAT</th><th>filing</th></tr></thead><tbody>
            {financials.data.map((r) => (
              <tr key={r.id}><td>{r.period_end.slice(0, 10)}{r.consolidated ? "" : " (S)"}</td><td>{fmt.num(r.values.revenue)}</td><td>{fmt.num(r.values.ebitda)}</td><td>{fmt.pct(r.ratios.ebitda_margin)}</td><td>{fmt.pct(r.ratios.revenue_yoy)}</td><td>{fmt.num(r.values.pat)}</td><td><Link href={docHref(r.raw_document_id)}>filing {r.filing_id}</Link></td></tr>
            ))}
          </tbody></table>
        </div>
      </section>

      {/* 4. Ownership trajectory */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Ownership trajectory</h2>
        <SeriesChart data={holdingSeries} keys={[{ key: "promoter", color: "#38bdf8", label: "promoter %" }, { key: "pledged", color: "#ff6b6b", label: "pledged % of promoter" }, { key: "institutions", color: "#3ddc97", label: "FII+DII %" }]} percent />
        <div className="grid grid-cols-3 gap-3 mt-3 text-[11px]">
          <div><div className="text-muted mb-1">Insider trades</div>{ownership.data.insider_trades.slice(0, 8).map((t) => <div key={t.id}>{fmt.date(t.public_at)} {String(t.fields.side)} ₹{fmt.num(Number(t.fields.value_inr) / 1e7)} cr <Link href={docHref(t.raw_document_id)}>doc</Link></div>)}{ownership.data.insider_trades.length === 0 && <div className="text-muted">none</div>}</div>
          <div><div className="text-muted mb-1">Pledge events</div>{ownership.data.pledge_events.slice(0, 8).map((e) => <div key={e.id}>{fmt.date(e.public_at)} {String(e.fields.event_type)} {fmt.num(Number(e.fields.pct_of_promoter_holding), 1)}% <Link href={docHref(e.raw_document_id)}>doc</Link></div>)}{ownership.data.pledge_events.length === 0 && <div className="text-muted">none</div>}</div>
          <div><div className="text-muted mb-1">Institutional holders / bulk deals</div>{ownership.data.shareholdings[0]?.holders.map((h) => <div key={h.name}>{h.name} {fmt.num(h.pct)}%</div>)}{ownership.data.bulk_deals.slice(0, 5).map((b) => <div key={b.id}>{fmt.date(b.public_at)} bulk {String(b.fields.side)} {String(b.fields.client)}</div>)}</div>
        </div>
      </section>

      {/* 5. Business */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Business</h2>
        {business ? (
          <>
            <table><thead><tr><th>order value ₹cr</th><th>execution</th><th>evidence</th></tr></thead><tbody>
              {(business.orders ?? []).map((o) => <tr key={o.evidence_id}><td>{fmt.num(o.value_cr)}</td><td>{o.execution_months ? `${o.execution_months} months` : "–"}</td><td><Link href={docHref(o.document_id, o.evidence_id)}>{o.quote}</Link></td></tr>)}
              <tr><td className="text-slate-100">{fmt.num(business.order_book_estimate_cr ?? 0)}</td><td className="text-muted" colSpan={2}>sum of verified orders (Python)</td></tr>
            </tbody></table>
            <div className="mt-2 text-[12px]">{business.capacity_story}</div>
          </>
        ) : <div className="text-muted">No Business agent run yet.</div>}
        <div className="mt-2 text-[11px] text-muted">Rating history: {ratingHistory.length ? ratingHistory.map((s) => `${fmt.date(s.public_at)} ${s.signal_type.replace("credit_rating_", "")} ${String(s.parameters.rating ?? "")}`).join(" · ") : "none"}</div>
      </section>

      {/* 6. Signals */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Signals</h2>
        <table><thead><tr><th>type</th><th>dir</th><th>mag</th><th>public</th><th>active</th><th>hit 180d</th><th>mean excess 180d</th><th>n</th><th>evidence</th></tr></thead><tbody>
          {signals.data.map((s) => {
            const h = s.performance?.horizons["180"] as Record<string, number | boolean> | undefined;
            return (
              <tr key={s.id} className={s.active ? "" : "text-muted"}>
                <td title={JSON.stringify(s.parameters)}>{s.signal_type}</td><td className={s.direction > 0 ? "text-pos" : s.direction < 0 ? "text-neg" : ""}>{s.direction > 0 ? "+" : s.direction < 0 ? "−" : "0"}</td><td>{s.magnitude.toFixed(2)}</td><td>{fmt.date(s.public_at)}</td><td>{s.active ? "yes" : ""}</td>
                <td>{h ? fmt.pct(h.hit_rate as number) : "–"}</td><td>{h ? fmt.pct(h.mean_excess as number) : "–"}</td><td className={h?.low_sample ? "text-warn" : ""}>{h ? `${h.n}${h.low_sample ? " (low)" : ""}` : "–"}</td>
                <td>{s.evidence_ids.map((eid) => <Link key={eid} href={docHref(evidenceMap.get(eid)?.raw_document_id ?? 0, eid)} className="kbd no-underline mr-1">ev {eid}</Link>)}</td>
              </tr>
            );
          })}
        </tbody></table>
      </section>

      {/* 7. Valuation scenarios */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Valuation scenarios</h2>
        {valuation ? <Suspense><ScenarioEditor valuation={valuation.data} /></Suspense> : <div className="text-muted">Insufficient data for scenarios.</div>}
      </section>

      {/* 8. Thesis and contradiction, side by side */}
      <section className="grid grid-cols-2 gap-3">
        <div className="card">
          <h2 className="text-slate-100 mb-2">Thesis</h2>
          {th ? (
            <dl className="text-[12px] space-y-1">
              {["key_change", "why_now", "what_market_may_be_missing", "strongest_positive", "strongest_negative", "what_would_break_this", "time_horizon", "confidence"].map((k) => <div key={k}><dt className="text-muted text-[10px] uppercase">{k.replace(/_/g, " ")}</dt><dd>{String(th[k])}</dd></div>)}
              <div className="mt-2"><Claims claims={(th.claims as Claim[]) ?? []} evidence={evidenceMap} companyId={cid} asOf={as_of} /></div>
            </dl>
          ) : <div className="text-muted">{thesis.data.message ?? "No thesis."}</div>}
        </div>
        <div className="card">
          <h2 className="text-slate-100 mb-2">Contradiction</h2>
          {co ? (
            <div className="text-[12px] space-y-2">
              <div>{co.case_against}</div>
              <div>thesis survives: <span className={co.thesis_survives === "yes" ? "text-pos" : co.thesis_survives === "no" ? "text-neg" : "text-warn"}>{co.thesis_survives}</span></div>
              <ol className="list-decimal ml-4 space-y-1">{co.disputed_claims.map((d, i) => <li key={i}><span className="text-muted">[{d.agent}]</span> {d.dispute} <span className="text-muted">Resolves with: {d.resolving_evidence}</span></li>)}</ol>
              <Claims claims={co.claims} evidence={evidenceMap} companyId={cid} asOf={as_of} />
            </div>
          ) : <div className="text-muted">No contradiction analysis.</div>}
        </div>
      </section>

      {/* 9. Forensic flags */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Forensic flags</h2>
        {forensic?.flags?.length ? forensic.flags.map((f, i) => (
          <div key={i} className="mb-2 text-[12px]"><span className={f.severity === "high" ? "text-neg" : "text-warn"}>{f.severity}</span> <span className="text-slate-100">{f.signal_type}</span> — {f.mechanism}<Claims claims={f.claims} evidence={evidenceMap} companyId={cid} asOf={as_of} /></div>
        )) : <div className="text-muted">{forensic ? "No flags." : "No Forensic agent run yet."}</div>}
      </section>

      {/* 10. Evidence viewer entry */}
      <section className="card">
        <h2 className="text-slate-100 mb-2">Evidence</h2>
        <table><thead><tr><th>id</th><th>source</th><th>public</th><th>created by</th><th>span</th></tr></thead><tbody>
          {[...evidenceMap.values()].map((e) => <tr key={e.id}><td><Link href={docHref(e.raw_document_id, e.id)}>ev {e.id}</Link></td><td>{e.source}</td><td>{fmt.date(e.public_at)}</td><td>{e.created_by}</td><td className="text-[11px]">{e.extracted_text.slice(0, 120)}</td></tr>)}
        </tbody></table>
      </section>
    </div>
  );
}
