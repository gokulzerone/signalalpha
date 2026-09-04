import Link from "next/link";
import type { DeskRow } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";

const READY: Record<string, [string, string]> = {
  ready: ["text-pos", "Ready to decide"],
  partial: ["text-caution", "Gaps to know about"],
  not_ready: ["text-ink-3", "Not ready"],
};

// One row per candidate. Three things carry the weight: which company, how strong the case is,
// and what changed. Everything else is one size down and grey.
export function RankedList({ rows, asOf }: { rows: DeskRow[]; asOf?: string }) {
  const q = asOf ? `?as_of=${asOf}` : "";
  return (
    <ol className="list-none p-0 m-0 card divide-y divide-rule overflow-hidden">
      {rows.map((r, i) => {
        const [tone, label] = READY[r.readiness.status];
        return (
          <li key={r.company_id}>
            <Link
              href={`/companies/${r.company_id}${q}`}
              className="group grid grid-cols-[2rem_1fr_auto] items-baseline gap-x-5 gap-y-2 px-6 py-5 no-underline hover:no-underline hover:bg-raised"
            >
              <span className="num text-[13px] text-ink-3 tabular-nums">{i + 1}</span>

              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-[17px] text-ink group-hover:underline">{r.name}</span>
                  <span className="num text-[12px] text-ink-3">
                    {r.ticker}
                    {r.sector && r.sector !== "Unclassified" ? ` · ${r.sector}` : ""} · {fmt.cr(r.market_cap_cr)}
                  </span>
                </span>
                <span className="block text-[14px] text-ink-2 mt-1 max-w-measure">{r.change}</span>
                <span className="block text-[12px] mt-2 flex flex-wrap gap-x-5 gap-y-1">
                  <span className={tone}>{label}</span>
                  {r.base_rate ? (
                    <span className="text-ink-3">
                      Signals like this:{" "}
                      <span className={`num ${Number(r.base_rate.mean_excess) > 0 ? "text-pos" : "text-neg"}`}>
                        {fmt.pct(r.base_rate.mean_excess as number)}
                      </span>{" "}
                      over 180 days, {String(r.base_rate.n)} events
                    </span>
                  ) : (
                    <span className="text-ink-3">No record of signals like this</span>
                  )}
                  {r.decision && <span className="text-link">marked {r.decision.verdict.replace("_", " ")}</span>}
                </span>
              </span>

              <span className="text-right">
                <span className={`num block text-[28px] leading-none ${scoreTone("opportunity", r.scores.opportunity)}`}>
                  {fmt.score(r.scores.opportunity)}
                  {r.opportunity_partial && <span className="text-caution text-[15px] align-super">*</span>}
                </span>
                <span className="label block mt-1">Opportunity</span>
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
