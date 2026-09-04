import Link from "next/link";
import { api, type DeskResponse } from "@/lib/api";
import { fmt } from "@/lib/format";
import { RankedList } from "@/components/RankedList";
import { Refresh } from "@/components/Refresh";

type Search = { as_of?: string; since?: string; sort?: string; all?: string };

// The landing page answers one question: which companies deserve my time, and why.
// It opens on a date this dataset can actually support, rather than on an empty today.
export default async function Desk({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const since = Number(sp.since ?? 180);
  const sort = sp.sort === "readiness" ? "readiness" : "opportunity";

  let desk = await api<DeskResponse>("/desk", { as_of: sp.as_of, since_days: since, limit: 25, sort });
  let asOf = sp.as_of;
  let movedDate: string | null = null;

  // Without an explicit date, land where the fundamentals were still current instead of on a
  // date whose filings are two years old.
  if (!sp.as_of && desk.data.coverage.suggested_as_of) {
    movedDate = fmt.date(desk.data.coverage.suggested_as_of);
    asOf = movedDate;
    desk = await api<DeskResponse>("/desk", { as_of: asOf, since_days: since, limit: 25, sort });
  }

  const { rows, coverage } = desk.data;
  const keep = asOf ? `as_of=${asOf}&` : "";
  const ready = rows.filter((r) => r.readiness.status === "ready").length;

  return (
    <div className="grid gap-4">
      <header className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
        <h1 className="text-[19px] text-slate-100">Most investable now</h1>
        <span className="text-[12px] text-muted">
          {rows.length} candidates from {coverage.covered_companies} covered companies · as of{" "}
          <span className="mono">{desk.as_of.slice(0, 10)}</span>
          {ready > 0 && <> · {ready} ready to decide</>}
        </span>
        <div className="ml-auto"><Refresh builtAt={new Date().toISOString()} /></div>
      </header>

      <p className="text-[13px] text-muted max-w-[85ch] m-0">
        Ranked by Opportunity: how much the fundamentals are changing, how far the accounts can be trusted, how cheap it
        is against its peers and its own history, and how little attention it gets, less a penalty for risk. Every
        number opens to its components. Click a row for the full reasoning and the filings behind it.
        {" "}
        <Link href={`/?${keep}sort=${sort === "opportunity" ? "readiness" : "opportunity"}&since=${since}`}>
          Sort by {sort === "opportunity" ? "readiness instead" : "opportunity instead"}
        </Link>
      </p>

      {movedDate && (
        <div className="panel text-[13px]">
          <span className="text-warn">Showing {movedDate}, not today.</span>{" "}
          <span className="text-muted">
            Prices and announcements are current, but the exchange&apos;s results feed stops at the quarter ending{" "}
            <span className="mono">{fmt.date(coverage.latest_fundamental_period_end)}</span>, so a view dated today
            would judge companies on filings {coverage.fundamentals_stale_days} days old. The{" "}
            <Link href="/data">data page</Link> shows freshness per source.
          </span>{" "}
          <Link href={`/?as_of=${new Date().toISOString().slice(0, 10)}&since=${since}`}>View today anyway</Link>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="panel">
          <h2 className="mb-2">Nothing to rank in this window</h2>
          <p className="text-[13px] max-w-[70ch] text-muted">
            {coverage.covered_companies === 0 ? (
              <>
                No company has fundamentals loaded, so nothing can be assessed. Run{" "}
                <span className="mono">scripts/sync_live.py</span> to ingest quarterly results.
              </>
            ) : (
              <>
                {coverage.covered_companies} companies have fundamentals loaded, and none disclosed a change in the last{" "}
                {since} days.
                {coverage.latest_signal_at && (
                  <> The most recent change on file is from <span className="mono">{fmt.date(coverage.latest_signal_at)}</span>.</>
                )}
              </>
            )}
          </p>
          {coverage.suggested_window_days && (
            <p className="mt-2 text-[13px]">
              <Link href={`/?${keep}since=${coverage.suggested_window_days}`}>
                Widen the window to {coverage.suggested_window_days} days
              </Link>
            </p>
          )}
        </div>
      ) : (
        <>
          <RankedList rows={rows} asOf={asOf} />
          {rows.some((r) => r.opportunity_partial) && (
            <p className="text-[11px] text-muted m-0">
              <span className="text-warn">*</span> The composite excludes{" "}
              {[...new Set(rows.flatMap((r) => r.opportunity_missing))].join(", ")}: the filings on file do not carry
              the data to measure it. A dash is an unmeasured component, never a bad one, and a partial score is not
              comparable with a complete one.
            </p>
          )}
        </>
      )}

      <p className="text-[11px] text-muted m-0">
        Looking for the unfiltered universe or the filters? <Link href={`/screener${asOf ? `?as_of=${asOf}` : ""}`}>Screener</Link>.
        Decisions you record are in the <Link href={`/journal${asOf ? `?as_of=${asOf}` : ""}`}>journal</Link>.
      </p>
    </div>
  );
}
