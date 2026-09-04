"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Capabilities, Investigation, InvestigationStage } from "@/lib/api";
import { fmt, scoreTone } from "@/lib/format";

// The page watches a run rather than pretending to: it polls the row the worker is writing,
// so the words on screen change only when a step has genuinely finished.
const MARK: Record<InvestigationStage["status"], string> = {
  pending: "○",
  running: "◍",
  done: "●",
  skipped: "◌",
  failed: "×",
};
const TONE: Record<InvestigationStage["status"], string> = {
  pending: "text-ink-3",
  running: "text-link",
  done: "text-pos",
  skipped: "text-caution",
  failed: "text-neg",
};

export function InvestigationPanel({ capabilities, asOf }: { capabilities: Capabilities; asOf?: string }) {
  const [run, setRun] = useState<Investigation | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(
    async (id: string) => {
      const res = await fetch(`/api/investigations/${id}${asOf ? `?as_of=${asOf}` : ""}`);
      if (!res.ok) return;
      const body = (await res.json()) as { data: Investigation };
      setRun(body.data);
      if (body.data.status === "queued" || body.data.status === "running") {
        timer.current = setTimeout(() => poll(id), 1200);
      }
    },
    [asOf],
  );

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const start = async () => {
    setStarting(true);
    setError(null);
    const res = await fetch(`/api/investigations${asOf ? `?as_of=${asOf}` : ""}`, { method: "POST" });
    setStarting(false);
    if (!res.ok) { setError(await res.text()); return; }
    const body = (await res.json()) as { data: Investigation };
    setRun(body.data);
    poll(body.data.id);
  };

  if (!run) {
    return (
      <div className="grid gap-8">
        <div className="grid gap-4 max-w-measure">
          <p className="prose m-0">
            An investigation works from the outside in. It reads what is happening in the world economy, works out
            what those conditions change, follows that into supply and demand, and only then looks for a listed
            Indian company standing in the path of it. Once it has one, it stops reading the web and reads that
            company&apos;s own filings: what the market is paying, what the numbers say, and what could go wrong.
          </p>
          <p className="text-[14px] text-ink-2 m-0">
            It takes a couple of minutes and ends with one company and the case for looking at it properly.
          </p>
        </div>

        <div>
          <button
            onClick={start}
            disabled={starting}
            className="px-6 py-3 rounded-md border border-link text-link text-[15px] hover:bg-raised disabled:opacity-40"
          >
            {starting ? "Starting" : "Start investigation"}
          </button>
          {error && <p className="text-[13px] text-neg mt-3 m-0">{error}</p>}
        </div>

        <div className="card divide-y divide-rule">
          {capabilities.stages.map((s, i) => (
            <div key={s.key} className="px-6 py-3 flex items-baseline gap-4">
              <span className="num text-[12px] text-ink-3 w-5">{i + 1}</span>
              <span className="text-[14px] text-ink-2">{s.done}</span>
              {s.needs_web && (
                <span className={`ml-auto text-[12px] ${capabilities.web_research ? "text-ink-3" : "text-caution"}`}>
                  {capabilities.web_research ? "reads the web" : "needs a key"}
                </span>
              )}
            </div>
          ))}
        </div>

        {!capabilities.web_research && (
          <p className="text-[13px] text-ink-2 max-w-measure m-0">
            The first three steps read the open web and need a Claude API key, which is not set here. Without it the
            investigation still runs: it says those steps were skipped and starts from the companies already covered,
            using their filings. {capabilities.how_to_enable}
          </p>
        )}
      </div>
    );
  }

  const r = run.result;
  const done = run.status === "completed";
  return (
    <div className="grid gap-8">
      <div className="flex items-baseline gap-4">
        <span className="text-[14px] text-ink-2">
          {run.status === "running" || run.status === "queued"
            ? run.stages.find((s) => s.status === "running")?.label ?? "Starting"
            : run.status === "failed"
              ? "The investigation stopped"
              : "Investigation complete"}
        </span>
        {(run.status === "running" || run.status === "queued") && (
          <span className="text-[13px] text-ink-3 num">
            {run.stages.filter((s) => s.status !== "pending" && s.status !== "running").length} of {run.stages.length}
          </span>
        )}
        <button onClick={() => setRun(null)} className="ml-auto text-[13px] text-ink-2 hover:text-ink">
          Start another
        </button>
      </div>

      <ol className="card divide-y divide-rule list-none p-0 m-0">
        {run.stages.map((s) => (
          <li key={s.key} className="px-6 py-4 grid grid-cols-[1.25rem_1fr] gap-4 items-baseline">
            <span className={`${TONE[s.status]} text-[13px] leading-none`} aria-hidden>
              {MARK[s.status]}
            </span>
            <div className="grid gap-2 min-w-0">
              <span className={`text-[14px] ${s.status === "pending" ? "text-ink-3" : "text-ink"}`}>{s.label}</span>
              {s.detail && <p className="text-[14px] text-ink-2 m-0 max-w-measure">{s.detail}</p>}

              {s.findings && s.findings.length > 0 && (
                <ul className="grid gap-2 list-none p-0 m-0">
                  {s.findings.map((f, i) => (
                    <li key={i} className="text-[13px] text-ink-2 max-w-measure">
                      <span className="text-ink">{f.condition}</span> {f.so_what}
                      {f.sectors.length > 0 && <span className="text-ink-3"> · {f.sectors.join(", ")}</span>}
                    </li>
                  ))}
                </ul>
              )}
              {s.sources && s.sources.length > 0 && (
                <p className="text-[12px] m-0 flex flex-wrap gap-x-4 gap-y-1">
                  {s.sources.slice(0, 6).map((src) => (
                    <a key={src.url} href={src.url} target="_blank" rel="noreferrer noopener">
                      {src.title.slice(0, 60)}
                    </a>
                  ))}
                </p>
              )}
              {s.shortlist && s.shortlist.length > 0 && (
                <p className="text-[12px] text-ink-3 m-0">
                  {s.shortlist.map((c) => c.ticker).join(" · ")}
                </p>
              )}
              {s.numbers && (
                <p className="text-[13px] text-ink-3 num m-0">
                  {Object.entries(s.numbers)
                    .filter(([, v]) => v !== null && v !== undefined)
                    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
                    .join("  ·  ")}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>

      {run.status === "failed" && (
        <p className="text-[14px] text-neg max-w-measure">{run.error?.split("\n")[0]}</p>
      )}

      {done && r && (
        <section className="grid gap-6">
          <div className="hairline pb-3 flex items-end justify-between gap-6">
            <div>
              <h2 className="text-[24px]">{r.company.name}</h2>
              <p className="num text-[13px] text-ink-3 m-0">
                {r.company.ticker}
                {r.company.sector && r.company.sector !== "Unclassified" ? ` · ${r.company.sector}` : ""}
              </p>
            </div>
            <div className="text-right">
              <div className={`num text-[34px] leading-none ${scoreTone("opportunity", r.scores.opportunity)}`}>
                {fmt.score(r.scores.opportunity)}
              </div>
              <div className="label mt-1">Opportunity</div>
            </div>
          </div>

          <p className="prose m-0">
            <strong className="font-semibold">{r.verdict.headline}</strong> {r.verdict.summary.join(" ")}
          </p>

          {r.macro_line && (
            <p className="text-[14px] text-ink-2 max-w-measure m-0">
              <span className="label">Why this corner of the market</span>
              <br />
              {r.macro_line}
            </p>
          )}
          <p className="text-[14px] text-ink-2 max-w-measure m-0">
            <span className="label">Why this company</span>
            <br />
            {r.why_this_one}
          </p>

          {r.verdict.caveats.length > 0 && (
            <ul className="grid gap-2 list-none p-0 m-0 max-w-measure">
              {r.verdict.caveats.map((c, i) => (
                <li key={i} className="text-[13px] text-ink-2 flex gap-3">
                  <span className="text-caution" aria-hidden>—</span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          )}

          <p className="text-[14px] m-0">
            <Link href={`/companies/${r.company.company_id}${asOf ? `?as_of=${asOf}` : ""}`}>
              Open the full company page
            </Link>
          </p>
        </section>
      )}
    </div>
  );
}
