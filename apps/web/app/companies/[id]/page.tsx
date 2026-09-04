import Link from "next/link";
import { api, type Brief, type Claim } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";
import { Scorecard } from "@/components/Scorecard";
import { DecideForm } from "@/components/DecideForm";

// The company page discloses in layers: the answer in plain words, then how it scores, then
// what happened and whether it is true, then everything underneath. A reader can stop at any
// layer and still have been told the truth, including what could not be measured.
export default async function CompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ as_of?: string }>;
}) {
  const { id } = await params;
  const { as_of } = await searchParams;
  const cid = Number(id);
  const res = await api<Brief>(`/companies/${cid}/brief`, { as_of, since_days: 200 });
  const b = res.data;
  const c = b.company;
  const q = as_of ? `?as_of=${as_of}` : "";
  const evidence = new Map(b.evidence.map((e) => [e.id, e]));
  const positives = b.narrated_signals.filter((s) => s.direction > 0).sort((a, x) => x.magnitude - a.magnitude);
  const negatives = b.narrated_signals.filter((s) => s.direction < 0).sort((a, x) => x.magnitude - a.magnitude);
  const co = b.thesis.contradiction?.output as { case_against?: string; thesis_survives?: string } | undefined;
  const rates = b.base_rates.filter((r) => r.horizon_days === 180);
  const opportunity = b.scores.find((s) => s.score_type === "opportunity")?.value ?? null;

  const source = (s: { evidence_ids: number[]; document_ids?: number[] }) => {
    if (s.evidence_ids.length) {
      const e = evidence.get(s.evidence_ids[0]);
      if (e)
        return (
          <Link
            className="text-[12px]"
            href={`/companies/${cid}/documents/${e.raw_document_id}?highlight=${e.id}${as_of ? `&as_of=${as_of}` : ""}`}
          >
            the passage
          </Link>
        );
    }
    const d = (s.document_ids ?? [])[0];
    return d ? (
      <Link className="text-[12px]" href={`/companies/${cid}/documents/${d}${q}`}>
        the filing
      </Link>
    ) : null;
  };

  const Section = ({ n, title, children, aside }: { n: string; title: string; children: React.ReactNode; aside?: string }) => (
    <section className="grid gap-4">
      <div className="flex items-baseline gap-4 hairline pb-2">
        <span className="num text-[12px] text-ink-3">{n}</span>
        <h2 className="text-[17px]">{title}</h2>
        {aside && <span className="ml-auto text-[12px] text-ink-3">{aside}</span>}
      </div>
      {children}
    </section>
  );

  return (
    <div className="grid gap-12">
      <header className="grid gap-6">
        <Link href={`/${q}`} className="text-[13px] text-ink-2">
          ← Candidates
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="grid gap-1">
            <h1 className="text-[32px] leading-tight">{c.name}</h1>
            <p className="num text-[13px] text-ink-3 m-0">
              {c.ticker}
              {c.sector && c.sector !== "Unclassified" ? ` · ${c.sector}` : ""} · {fmt.cr(c.market_cap_cr)} · ₹
              {fmt.num(c.price)} on {fmt.date(c.price_date)}
            </p>
          </div>
          <div className="text-right">
            <div className={`num text-[44px] leading-none ${scoreTone("opportunity", opportunity)}`}>
              {fmt.score(opportunity)}
            </div>
            <div className="label mt-1">Opportunity</div>
          </div>
        </div>
      </header>

      <Section n="01" title="The short version">
        <p className="prose m-0">
          <strong className="font-semibold">{b.verdict.headline}</strong> {b.verdict.summary.join(" ")}
        </p>
        {b.verdict.caveats.length > 0 && (
          <ul className="grid gap-2 list-none p-0 m-0 max-w-measure">
            {b.verdict.caveats.map((cv, i) => (
              <li key={i} className="text-[13px] text-ink-2 flex gap-3">
                <span className="text-caution" aria-hidden>
                  —
                </span>
                <span>{cv}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section n="02" title="How it scores" aside="open a row for the components">
        <Scorecard verdict={b.verdict} scores={b.scores} />
      </Section>

      <Section n="03" title="What changed" aside="each line opens the filing it came from">
        <div className="card divide-y divide-rule">
          {positives.length === 0 && negatives.length === 0 && (
            <p className="px-6 py-5 text-[14px] text-ink-2 m-0">No signals in this window.</p>
          )}
          {[...positives, ...negatives].slice(0, 10).map((s) => (
            <div key={s.signal_id} className="px-6 py-4 flex gap-4 items-baseline">
              <span className={`num text-[13px] ${s.direction > 0 ? "text-pos" : "text-neg"}`} aria-hidden>
                {s.direction > 0 ? "+" : "−"}
              </span>
              <span className="text-[14px] flex-1">{s.sentence}</span>
              <span className="num text-[12px] text-ink-3 whitespace-nowrap">{fmt.date(s.public_at)}</span>
              {source(s)}
            </div>
          ))}
        </div>
      </Section>

      <Section n="04" title="The case against">
        {co?.case_against ? (
          <>
            <p className="prose text-ink-2 m-0">{co.case_against}</p>
            <p className="text-[13px] m-0">
              Thesis survives:{" "}
              <span className={co.thesis_survives === "yes" ? "text-pos" : co.thesis_survives === "no" ? "text-neg" : "text-caution"}>
                {co.thesis_survives}
              </span>
            </p>
          </>
        ) : (
          <p className="text-[14px] text-ink-2 m-0">No contradiction analysis has been produced yet.</p>
        )}
        {b.forensic_flags.length > 0 && (
          <ul className="grid gap-2 list-none p-0 m-0">
            {b.forensic_flags.map((f, i) => (
              <li key={i} className="text-[14px] max-w-measure">
                <span className={f.severity === "high" ? "text-neg" : "text-caution"}>{f.severity}</span>{" "}
                <span className="text-ink">{String(f.signal_type).replace(/_/g, " ")}</span>
                <span className="text-ink-2"> — {f.mechanism}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section n="05" title="What history says" aside="excess return against the universe, 180 days">
        {rates.length ? (
          <div className="card px-6 py-2 scroll-x">
            <table className="text-[14px]">
              <thead>
                <tr>
                  <th>Signal</th>
                  <th className="n">Events</th>
                  <th className="n">Hit rate</th>
                  <th className="n">Median excess</th>
                  <th className="n">95% range</th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r) => (
                  <tr key={r.signal_type} className={r.low_sample ? "text-ink-3" : ""}>
                    <td>{r.signal_type.replace(/_/g, " ")}</td>
                    <td className="n">
                      {r.n}
                      {r.low_sample ? " thin" : ""}
                    </td>
                    <td className="n">{fmt.pct(r.hit_rate)}</td>
                    <td className={`n ${(r.median_excess ?? 0) > 0 ? "text-pos" : "text-neg"}`}>{fmt.pct(r.median_excess)}</td>
                    <td className="n text-ink-3">
                      {fmt.pct(r.ci_low)} to {fmt.pct(r.ci_high)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[14px] text-ink-2 max-w-measure m-0">
            No backtest record for these signal types yet, so there is nothing to say about how they played out before.
          </p>
        )}
      </Section>

      <Section n="06" title="What it would take to act" aside="arithmetic, not advice">
        <div className="card p-6 grid gap-5">
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              ["Traded per day", fmt.rupees(b.liquidity.adv_inr)],
              ["Exiting ₹10 lakh", fmt.days(b.liquidity.days_to_exit?.["10L"])],
              ["Round trip cost", fmt.pct(b.liquidity.round_trip_cost_pct, 2)],
            ].map(([k, v]) => (
              <div key={k}>
                <div className="label">{k}</div>
                <div className="num text-[19px] mt-1">{v}</div>
              </div>
            ))}
          </div>
          {b.break_conditions.length > 0 && (
            <div>
              <div className="label mb-2">What would change your mind</div>
              <ul className="grid gap-1 list-none p-0 m-0">
                {b.break_conditions.map((x, i) => (
                  <li key={i} className="text-[14px] text-ink-2 max-w-measure">
                    {x.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Section>

      <Section n="07" title="Your decision" aside="recorded with the evidence as it stands">
        <div className="card p-6">
          <DecideForm
            companyId={cid}
            suggestedReviewBy={b.suggested_review_by}
            asOf={as_of}
            defaultTrigger={b.break_conditions[0]?.text ?? "The next quarterly result reverses the change above."}
          />
          {b.decisions.length > 0 && (
            <ul className="mt-6 pt-5 hairline border-t border-rule grid gap-2 list-none p-0">
              {b.decisions.map((d) => (
                <li key={d.id} className="text-[13px]">
                  <span className="text-ink">{d.verdict.replace("_", " ")}</span>
                  <span className="text-ink-2"> — {d.reason}</span>
                  <span className="num text-ink-3"> · {fmt.date(d.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      <section className="hairline border-t border-rule pt-6 flex flex-wrap gap-x-8 gap-y-2 text-[13px]">
        <Link href={`/companies/${cid}/research${q}`}>Every figure, chart and filing</Link>
        <span className="text-ink-3">
          {b.evidence.length} stored passages · readiness: {b.readiness.headline.toLowerCase()}
        </span>
      </section>
    </div>
  );
}
