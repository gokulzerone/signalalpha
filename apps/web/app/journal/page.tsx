import Link from "next/link";
import { api, type Alert, type Decision } from "@/lib/api";
import { fmt } from "@/lib/format";

const TONE: Record<string, string> = { shortlist: "text-pos", track: "text-warn", needs_evidence: "text-warn", pass: "text-muted" };

// What you decided, why, and what has happened since. The record is what makes the next
// decision better; without it there is nothing to learn from.
export default async function Journal({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const { as_of } = await searchParams;
  const [decisions, alerts] = await Promise.all([
    api<Decision[]>("/decisions", { as_of }),
    api<Alert[]>("/decisions/alerts", { as_of }),
  ]);
  const q = as_of ? `?as_of=${as_of}` : "";
  const byCompany = new Map<number, Alert[]>();
  for (const a of alerts.data) byCompany.set(a.decision.company_id, [...(byCompany.get(a.decision.company_id) ?? []), a]);

  return (
    <div className="grid gap-4 max-w-5xl">
      <div className="note">
        Every decision you recorded, with what has happened since. Alerts fire when a name you kept
        throws a negative signal, or when a review you set comes due. <Link href={`/${q}`}>Back to the desk</Link>
      </div>

      <section className="panel">
        <h2>Needs your attention <span className="muted">({alerts.data.length})</span></h2>
        {alerts.data.length === 0 ? <div className="empty">Nothing has broken and no review is due.</div> : (
          <ul className="claims text-[13px]">
            {alerts.data.map((a, i) => (
              <li key={i}>
                <Link href={`/companies/${a.decision.company_id}/brief${q}`}>{a.decision.name}</Link>{" "}
                <span className={a.kind === "review_due" ? "warn" : "neg"}>{a.kind === "review_due" ? "review due" : "new negative signal"}</span>{" "}
                {a.text} <span className="tick">{fmt.date(a.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Decisions <span className="muted">({decisions.data.length})</span></h2>
        {decisions.data.length === 0 ? (
          <div className="empty">Nothing recorded yet. Open a brief from the desk and write down what you concluded, even if it is &ldquo;pass&rdquo;.</div>
        ) : (
          <div className="tbl"><table>
            <thead><tr><th>company</th><th>verdict</th><th>conviction</th><th>why</th><th>watching for</th><th>review by</th><th>recorded</th><th className="n">since</th></tr></thead>
            <tbody>
              {decisions.data.map((d) => {
                const fired = (byCompany.get(d.company_id) ?? []).filter((a) => a.kind === "negative_signal").length;
                return (
                  <tr key={d.id}>
                    <td><Link href={`/companies/${d.company_id}/brief${q}`}>{d.name}</Link><div className="tick">{d.ticker}</div></td>
                    <td className={TONE[d.verdict]}>{d.verdict.replace("_", " ")}</td>
                    <td className="muted">{d.conviction ?? "–"}</td>
                    <td className="max-w-[36ch]">{d.reason}</td>
                    <td className="max-w-[30ch] text-muted">{d.review_trigger ?? "–"}</td>
                    <td className="mono">{fmt.date(d.review_by)}</td>
                    <td className="mono">{fmt.date(d.created_at)}</td>
                    <td className={`n ${fired ? "neg" : "muted"}`}>{fired ? `${fired} negative` : "quiet"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
