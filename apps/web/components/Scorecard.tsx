import type { Brief, ScoreOut } from "@/lib/api";
import { fmt } from "@/lib/format";
import { ScoreBar } from "./ScoreBar";

// Each factor states its score, what that score means in words, and what it was measuring.
// Opening a row shows the components the score was built from, so a number is never a
// black box and an unmeasured one says so.
export function Scorecard({ verdict, scores }: { verdict: Brief["verdict"]; scores: ScoreOut[] }) {
  const byType = new Map(scores.map((s) => [s.score_type, s]));
  return (
    <div className="card divide-y divide-rule">
      {verdict.factors.map((f) => {
        const detail = byType.get(f.key);
        const components = detail ? Object.entries(detail.components.components) : [];
        return (
          <details key={f.key} className="group">
            <summary className="grid grid-cols-[7rem_auto_1fr] items-center gap-x-5 px-6 py-4 hover:bg-raised">
              <span className="text-[14px] text-ink">{f.label}</span>
              <ScoreBar value={f.value} scoreType={f.key} />
              <span className="flex items-baseline gap-3 min-w-0">
                <span className={`text-[14px] ${f.measured ? "text-ink-2" : "text-ink-3"}`}>{f.verdict}</span>
                <span className="ml-auto text-[12px] text-ink-3 group-open:hidden">Why</span>
                <span className="ml-auto text-[12px] text-ink-3 hidden group-open:inline">Close</span>
              </span>
            </summary>
            <div className="px-6 pb-5 pt-1 grid gap-3">
              <p className="text-[13px] text-ink-2 max-w-measure m-0">{f.measures}.</p>
              {components.length > 0 ? (
                <div className="scroll-x">
                  <table className="text-[13px]">
                    <thead>
                      <tr>
                        <th>Component</th>
                        <th className="n">Measured</th>
                        <th className="n">Percentile</th>
                        <th className="n">Weight</th>
                      </tr>
                    </thead>
                    <tbody>
                      {components.map(([k, c]) => (
                        <tr key={k}>
                          <td className="text-ink-2">{k.replace(/_/g, " ")}</td>
                          <td className="n">{fmt.num(c.raw, 3)}</td>
                          <td className="n">{fmt.score(c.percentile)}</td>
                          <td className="n text-ink-3">{c.weight}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-[13px] text-caution max-w-measure m-0">
                  Nothing to show: the inputs this factor reads are not in the filings held for this company.
                </p>
              )}
              <p className="text-[12px] text-ink-3 m-0">
                Scores are percentiles against every company in the universe on this date, so 60 means it ranks ahead of
                60% of them.
              </p>
            </div>
          </details>
        );
      })}
    </div>
  );
}
