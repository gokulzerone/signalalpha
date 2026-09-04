import Link from "next/link";
import { api, type DeskRow } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";
import { ReadinessBadge } from "@/components/Readiness";

// The desk: a short queue of what changed, each item saying whether it can be decided on yet.
export default async function Desk({ searchParams }: { searchParams: Promise<{ as_of?: string; since?: string; all?: string }> }) {
  const sp = await searchParams;
  const since = Number(sp.since ?? 30);
  const desk = await api<DeskRow[]>("/desk", { as_of: sp.as_of, since_days: since, limit: 12, include_decided: sp.all === "1" ? "true" : undefined });
  const q = sp.as_of ? `?as_of=${sp.as_of}` : "";
  const ready = desk.data.filter((r) => r.readiness.status !== "not_ready");
  const blocked = desk.data.filter((r) => r.readiness.status === "not_ready");

  const Card = ({ r }: { r: DeskRow }) => (
    <article className="panel grid gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link href={`/companies/${r.company_id}/brief${q}`} className="text-[15px] text-slate-100 no-underline hover:underline">{r.name}</Link>
        <span className="tick">{r.ticker} · {r.sector} · {fmt.cr(r.market_cap_cr)}</span>
        <span className="ml-auto flex items-center gap-2">
          <ReadinessBadge readiness={r.readiness} />
          {r.decision && <span className="pill on">{r.decision.verdict.replace("_", " ")}</span>}
        </span>
      </div>
      <p className="text-[13px] max-w-[75ch]">{r.change}</p>
      <div className="grid grid-cols-2 gap-3 text-[12px]">
        <div><span className="text-muted text-[10px] uppercase tracking-wide block">Strongest for</span><span className="pos">{r.for_case}</span></div>
        <div><span className="text-muted text-[10px] uppercase tracking-wide block">Strongest against</span><span className="neg">{r.against_case}</span></div>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-muted">
        <span>Opportunity <b className={scoreTone("opportunity", r.scores.opportunity)}>{fmt.score(r.scores.opportunity)}</b></span>
        <span>Risk <b className={scoreTone("risk", r.scores.risk)}>{fmt.score(r.scores.risk)}</b></span>
        {r.base_rate ? (
          <span>
            Signals like this, 180d: <b className={Number(r.base_rate.mean_excess) > 0 ? "pos" : "neg"}>{fmt.pct(r.base_rate.mean_excess as number)}</b> median excess,{" "}
            {fmt.pct(r.base_rate.hit_rate as number, 0)} hit rate, n={String(r.base_rate.n)}{r.base_rate.low_sample ? " (thin)" : ""}
          </span>
        ) : <span>No history for this signal type.</span>}
        {r.readiness.status !== "ready" && <span className="warn">{r.readiness.headline}</span>}
      </div>
      <Link href={`/companies/${r.company_id}/brief${q}`} className="text-[12px] no-underline text-accent">Open the brief →</Link>
    </article>
  );

  return (
    <div className="grid gap-4">
      <div className="note">
        Your desk for {desk.as_of.slice(0, 10)}. Companies whose facts changed in the last {since} days, most decidable first.
        Each card says what changed, the strongest point either way, and what history says about signals of that kind.
        {" "}<Link href={`/screener${q}`}>Full screener</Link> · <Link href={`/journal${q}`}>Journal</Link>
      </div>
      {desk.data.length === 0 && <div className="panel empty">Nothing changed in this window. Widen it with <span className="mono">?since=90</span>.</div>}
      {ready.length > 0 && (
        <section className="grid gap-3">
          <h2>Ready for a view <span className="muted">({ready.length})</span></h2>
          {ready.map((r) => <Card key={r.company_id} r={r} />)}
        </section>
      )}
      {blocked.length > 0 && (
        <section className="grid gap-3">
          <h2>Something is missing <span className="muted">({blocked.length})</span></h2>
          <div className="tick">These changed too, but the research is not complete enough to form a view. Each says what it is waiting for.</div>
          {blocked.map((r) => <Card key={r.company_id} r={r} />)}
        </section>
      )}
    </div>
  );
}
