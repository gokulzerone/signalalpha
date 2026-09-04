import Link from "next/link";
import type { DeskRow } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";

const READY: Record<string, [string, string]> = {
  ready: ["text-pos border-pos", "Ready to decide"],
  partial: ["text-warn border-warn", "Gaps to know about"],
  not_ready: ["text-neg border-neg", "Not ready"],
};

// One row per candidate, ranked. The three things a reader scans for come first and loudest:
// which company, how strong the case is, and what actually changed. Everything else is
// supporting detail at a smaller size.
export function RankedList({ rows, asOf }: { rows: DeskRow[]; asOf?: string }) {
  const q = asOf ? `?as_of=${asOf}` : "";
  return (
    <ol className="grid gap-2 list-none p-0 m-0">
      {rows.map((r, i) => {
        const [tone, label] = READY[r.readiness.status];
        const parts: [string, number | null][] = [
          ["Inflection", r.scores.inflection],
          ["Quality", r.scores.quality],
          ["Valuation", r.scores.valuation],
          ["Attention", r.scores.attention_gap],
          ["Risk", r.scores.risk],
        ];
        return (
          <li key={r.company_id}>
            <Link
              href={`/companies/${r.company_id}/brief${q}`}
              className="no-underline block panel hover:border-accent transition-colors"
            >
              <div className="flex gap-4 items-start">
                <div className="mono text-[22px] text-muted w-9 shrink-0 text-right leading-none pt-1">{i + 1}</div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <span className="text-[17px] text-slate-100">{r.name}</span>
                    <span className="tick">
                      {r.ticker}
                      {r.sector && r.sector !== "Unclassified" ? ` · ${r.sector}` : ""} · {fmt.cr(r.market_cap_cr)}
                    </span>
                  </div>
                  <p className="text-[14px] mt-1 mb-0 max-w-[78ch]">{r.change}</p>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[11px] text-muted">
                    <span className={`pill ${tone}`} style={{ borderColor: "currentColor" }}>{label}</span>
                    {r.base_rate ? (
                      <span>
                        Signals like this over 180 days:{" "}
                        <b className={Number(r.base_rate.mean_excess) > 0 ? "text-pos" : "text-neg"}>
                          {fmt.pct(r.base_rate.mean_excess as number)}
                        </b>{" "}
                        excess, {String(r.base_rate.n)} events{r.base_rate.low_sample ? ", thin" : ""}
                      </span>
                    ) : (
                      <span>No history for this signal type.</span>
                    )}
                    {r.decision && <span className="text-accent">you marked this {r.decision.verdict.replace("_", " ")}</span>}
                    <span className="text-accent">Why →</span>
                  </div>
                </div>

                <div className="shrink-0 text-right pl-2 border-l border-rule">
                  <div className="text-[10px] uppercase tracking-wider text-muted">
                    Opportunity{r.opportunity_partial && <span className="text-warn" title={`${r.opportunity_missing.join(", ")} could not be measured from the filings on file`}> *</span>}
                  </div>
                  <div className={`mono text-[30px] leading-none ${scoreTone("opportunity", r.scores.opportunity)}`}>
                    {fmt.score(r.scores.opportunity)}
                  </div>
                  <dl className="mt-2 grid grid-cols-[auto_auto] gap-x-2 text-[11px] text-right">
                    {/* A dash below means the data to measure it is not on file, not a bad score. */}
                    {parts.map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="text-muted">{k}</dt>
                        <dd className={`mono m-0 ${scoreTone(k.toLowerCase() === "attention" ? "attention_gap" : k.toLowerCase(), v)}`}>
                          {fmt.score(v)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
