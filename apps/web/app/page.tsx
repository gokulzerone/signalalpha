import Link from "next/link";
import { api, type DeskResponse, type DeskRow } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";
import { ReadinessBadge } from "@/components/Readiness";

// The desk: a short queue of what changed, each item saying whether it can be decided on yet.
export default async function Desk({ searchParams }: { searchParams: Promise<{ as_of?: string; since?: string; all?: string }> }) {
  const sp = await searchParams;
  const since = Number(sp.since ?? 30);
  const desk = await api<DeskResponse>("/desk", { as_of: sp.as_of, since_days: since, limit: 12, include_decided: sp.all === "1" ? "true" : undefined });
  const { rows, coverage } = desk.data;
  const q = sp.as_of ? `?as_of=${sp.as_of}` : "";
  const ready = rows.filter((r) => r.readiness.status !== "not_ready");
  const blocked = rows.filter((r) => r.readiness.status === "not_ready");
  const widen = coverage.suggested_window_days;
  const keep = sp.as_of ? `as_of=${sp.as_of}&` : "";
  const staleAsOf = coverage.suggested_as_of ? fmt.date(coverage.suggested_as_of) : null;

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
      {staleAsOf && (
        <div className="panel" style={{ borderLeft: "3px solid var(--tw-warn, #ffc857)" }}>
          <div className="text-warn text-[13px]">
            You are looking at a date {coverage.fundamentals_stale_days} days past the newest results on file.
          </div>
          <p className="text-[13px] text-muted max-w-[75ch] mt-1">
            Prices and announcements are current, but the newest reported quarter ends{" "}
            <span className="mono">{fmt.date(coverage.latest_fundamental_period_end)}</span>, so nothing here can be
            judged on current fundamentals. The exchange&apos;s results feed serves nothing newer; the{" "}
            <Link href="/data">data page</Link> shows freshness per source.
          </p>
          <p className="text-[13px] mt-2">
            <Link href={`/?as_of=${staleAsOf}&since=200`}>View as of {staleAsOf}</Link>, when these fundamentals were
            current.
          </p>
        </div>
      )}
      {rows.length === 0 && (
        <div className="panel">
          <h2 className="mb-2">Nothing to decide on in this window</h2>
          <p className="text-[13px] max-w-[70ch] text-muted">
            {coverage.covered_companies === 0 ? (
              <>No company has fundamentals loaded yet, so nothing can be assessed. Run <span className="mono">scripts/sync_live.py</span> to ingest quarterly results, or switch to the mock universe.</>
            ) : (
              <>
                {coverage.covered_companies} companies have fundamentals loaded, and none of them disclosed a change in the last {since} days.
                {coverage.latest_signal_at && <> The most recent change on file is from <span className="mono">{fmt.date(coverage.latest_signal_at)}</span>.</>}
                {coverage.latest_fundamental_period_end && <> The newest reported quarter ends <span className="mono">{fmt.date(coverage.latest_fundamental_period_end)}</span>.</>}
              </>
            )}
          </p>
          {widen && (
            <p className="mt-2 text-[13px]">
              <Link href={`/?${keep}since=${widen}`}>Widen the window to {widen} days</Link> to see what did change.
            </p>
          )}
        </div>
      )}
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
