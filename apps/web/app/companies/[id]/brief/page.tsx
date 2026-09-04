import Link from "next/link";
import { api, type Brief, type Claim } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";
import { ReadinessList } from "@/components/Readiness";
import { DecideForm } from "@/components/DecideForm";
import { Claims } from "@/components/Claims";

// The brief runs in the order a person actually decides: what changed, is it true, can the
// business be trusted, what does the price assume, what is the case against, what did signals
// like this do before, how much could I even trade, and what would change my mind.
export default async function BriefPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ as_of?: string }> }) {
  const { id } = await params;
  const { as_of } = await searchParams;
  const cid = Number(id);
  const res = await api<Brief>(`/companies/${cid}/brief`, { as_of });
  const b = res.data;
  const q = as_of ? `?as_of=${as_of}` : "";
  const evidence = new Map(b.evidence.map((e) => [e.id, e]));
  const positives = b.narrated_signals.filter((s) => s.direction > 0).sort((a, x) => x.magnitude - a.magnitude);
  const negatives = b.narrated_signals.filter((s) => s.direction < 0).sort((a, x) => x.magnitude - a.magnitude);
  const co = b.thesis.contradiction?.output as { case_against?: string; thesis_survives?: string } | undefined;
  const byHorizon = b.base_rates.filter((r) => r.horizon_days === 180);
  const step = (n: number, title: string, sub?: string) => (
    <div className="flex items-baseline gap-3 mb-2">
      <span className="mono text-accent text-[11px]">{String(n).padStart(2, "0")}</span>
      <h2>{title}</h2>
      {sub && <span className="tick">{sub}</span>}
    </div>
  );
  // A quoted span links to the highlighted passage; a table-derived figure links to the filing.
  const sourceLinks = (s: { evidence_ids: number[]; document_ids: number[] }) => {
    if (s.evidence_ids.length) {
      return s.evidence_ids.map((eid) => {
        const e = evidence.get(eid);
        return <Link key={eid} className="ev" href={`/companies/${cid}/documents/${e?.raw_document_id ?? 0}?highlight=${eid}${as_of ? `&as_of=${as_of}` : ""}`} title={e?.extracted_text ?? ""}>read the passage</Link>;
      });
    }
    return s.document_ids.slice(0, 1).map((did) => (
      <Link key={did} className="ev" href={`/companies/${cid}/documents/${did}${q}`}>open the filing</Link>
    ));
  };

  return (
    <div className="grid gap-4 max-w-5xl">
      <div className="note">
        <Link href={`/${q}`}>← desk</Link> · <Link href={`/companies/${cid}${q}`}>full research page</Link> · as of {res.as_of.slice(0, 10)}
      </div>

      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1>{b.company.name}</h1>
        <span className="tick">{b.company.ticker} · {b.company.sector} · {fmt.cr(b.company.market_cap_cr)} · ₹{fmt.num(b.company.price)}</span>
      </header>

      <section className="panel">
        {step(1, "What changed")}
        <p className="text-[15px] max-w-[70ch]">{b.change}</p>
        <div className="tick mt-1">{b.change_at ? `Disclosed ${fmt.date(b.change_at)}.` : "No dated change in this window."}</div>
      </section>

      <section className="panel">
        {step(2, "Is it true?", "every line below is a filing you can open")}
        <div className="grid gap-1 text-[13px]">
          {positives.slice(0, 6).map((s) => (
            <div key={s.signal_id} className="flex gap-2"><span className="pos" aria-hidden>+</span><span>{s.sentence} <span className="tick">{fmt.date(s.public_at)}</span> {sourceLinks(s)}</span></div>
          ))}
          {positives.length === 0 && <div className="muted">No positive signals in this window.</div>}
        </div>
      </section>

      <section className="panel">
        {step(3, "Can the business be trusted?")}
        <div className="flex flex-wrap gap-5 mb-2">
          {b.scores.filter((s) => ["quality", "risk"].includes(s.score_type)).map((s) => (
            <span key={s.score_type} className="text-[12px] text-muted">{s.score_type} <b className={`text-[16px] ${scoreTone(s.score_type, s.value)}`}>{fmt.score(s.value)}</b></span>
          ))}
        </div>
        {b.forensic_flags.length ? b.forensic_flags.map((f, i) => (
          <div key={i} className="text-[13px] mb-2">
            <b className={f.severity === "high" ? "neg" : "warn"}>{f.severity}</b> <b>{f.signal_type.replace(/_/g, " ")}</b> — {f.mechanism}
            <Claims claims={f.claims as Claim[]} evidence={evidence} companyId={cid} asOf={as_of} />
          </div>
        )) : <div className="text-[13px] pos">No accounting flags are active.</div>}
      </section>

      <section className="panel">
        {step(4, "What does the price already assume?")}
        {b.valuation ? (
          <div className="tbl"><table>
            <thead><tr><th>scenario</th><th className="n">growth</th><th className="n">margin</th><th className="n">exit multiple</th><th className="n">value / share</th><th className="n">vs today</th></tr></thead>
            <tbody>{b.valuation.scenarios.map((s) => (
              <tr key={s.name}><td>{s.name}</td><td className="n">{fmt.pct(Number(s.assumptions.revenue_growth))}</td><td className="n">{fmt.pct(Number(s.assumptions.ebitda_margin))}</td>
                <td className="n">{fmt.num(s.assumptions.exit_ev_ebitda, 1)}x</td><td className="n mono">₹{fmt.num(s.value_per_share)}</td>
                <td className={`n ${s.implied_change_vs_price >= 0 ? "pos" : "neg"}`}>{fmt.pct(s.implied_change_vs_price)}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <div className="muted text-[13px]">Not enough data for scenarios.</div>}
        <div className="tick mt-1">Scenarios are arithmetic from stated assumptions, not forecasts. Edit them on the <Link href={`/companies/${cid}${q}`}>research page</Link>.</div>
      </section>

      <section className="panel">
        {step(5, "The case against")}
        {co?.case_against ? (
          <>
            <p className="text-[13px] max-w-[70ch]">{co.case_against}</p>
            <div className="text-[12px] mt-1">Thesis survives: <b className={co.thesis_survives === "yes" ? "pos" : co.thesis_survives === "no" ? "neg" : "warn"}>{co.thesis_survives}</b></div>
          </>
        ) : <div className="muted text-[13px]">No contradiction analysis yet. Run the research job before deciding.</div>}
        <div className="grid gap-1 text-[13px] mt-2">
          {negatives.slice(0, 5).map((s) => (
            <div key={s.signal_id} className="flex gap-2"><span className="neg" aria-hidden>−</span><span>{s.sentence} <span className="tick">{fmt.date(s.public_at)}</span> {sourceLinks(s)}</span></div>
          ))}
        </div>
      </section>

      <section className="panel">
        {step(6, "What happened last time", "forward excess return over the benchmark, from the backtest")}
        {byHorizon.length ? (
          <div className="tbl"><table>
            <thead><tr><th>signal type</th><th className="n">events</th><th className="n">hit rate</th><th className="n">median excess 180d</th><th className="n">95% CI</th></tr></thead>
            <tbody>{byHorizon.map((r) => (
              <tr key={r.signal_type} className={r.low_sample ? "muted" : ""}>
                <td>{r.signal_type.replace(/_/g, " ")}</td><td className="n">{r.n}{r.low_sample ? " ⚠" : ""}</td>
                <td className="n">{fmt.pct(r.hit_rate)}</td><td className={`n ${(r.median_excess ?? 0) > 0 ? "pos" : "neg"}`}>{fmt.pct(r.median_excess)}</td>
                <td className="n">{fmt.pct(r.ci_low)} … {fmt.pct(r.ci_high)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <div className="muted text-[13px]">No backtest record for these signal types yet.</div>}
        <div className="tick mt-1">Greyed rows have fewer than 30 events: treat them as anecdote, not evidence.</div>
      </section>

      <section className="panel">
        {step(7, "How much could you even trade?")}
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-[13px]">
          <span className="text-muted">Traded value <b className="text-slate-200">₹{fmt.num(b.liquidity.adv_inr, 0)}/day</b></span>
          <span className="text-muted">At {b.liquidity.participation_pct}% participation <b className="text-slate-200">₹{fmt.num(b.liquidity.comfortable_position_inr, 0)}/day</b></span>
          <span className="text-muted">Round trip cost <b className="text-slate-200">{fmt.pct(b.liquidity.round_trip_cost_pct, 2)}</b></span>
          {b.liquidity.illiquid && <span className="warn">Below the liquidity floor.</span>}
        </div>
        <div className="tbl mt-2"><table>
          <thead><tr><th>position</th>{Object.keys(b.liquidity.days_to_exit).map((k) => <th key={k} className="n">₹{k}</th>)}</tr></thead>
          <tbody><tr><td className="text-muted">trading days to exit</td>{Object.entries(b.liquidity.days_to_exit).map(([k, v]) => <td key={k} className="n">{Number.isFinite(v) ? (v < 1 ? "under a day" : v) : "–"}</td>)}</tr></tbody>
        </table></div>
      </section>

      <section className="panel">
        {step(8, "What would change your mind")}
        <ul className="claims text-[13px]">
          {b.break_conditions.map((c, i) => <li key={i}>{c.text} <span className="tick">({c.source})</span></li>)}
          {b.break_conditions.length === 0 && <li className="muted">None recorded yet.</li>}
        </ul>
      </section>

      <section className="panel">
        {step(9, "Where the research stands")}
        <div className="mb-2 text-[13px]">{b.readiness.headline}</div>
        <ReadinessList readiness={b.readiness} />
      </section>

      <section className="panel">
        {step(10, "Your decision", "recorded with the evidence as it stands today")}
        <DecideForm companyId={cid} suggestedReviewBy={b.suggested_review_by} asOf={as_of}
          defaultTrigger={b.break_conditions[0]?.text ?? "The next quarterly result reverses the change above."} />
        {b.decisions.length > 0 && (
          <div className="mt-4">
            <h3>Earlier decisions</h3>
            <ul className="claims text-[12px]">
              {b.decisions.map((d) => (
                <li key={d.id}><span className="pill on">{d.verdict.replace("_", " ")}</span> {d.reason} <span className="tick">{fmt.date(d.created_at)}{d.review_by ? ` · review by ${fmt.date(d.review_by)}` : ""}</span></li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
