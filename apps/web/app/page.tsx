import Link from "next/link";
import { api, type DeskResponse } from "@/lib/api";
import { fmt } from "@/lib/format";
import { RankedList } from "@/components/RankedList";
import { Refresh } from "@/components/Refresh";

type Search = { as_of?: string; since?: string; sort?: string };

// One question, answered in order: which of these deserves my time, and why.
export default async function Candidates({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const since = Number(sp.since ?? 180);
  const sort = sp.sort === "readiness" ? "readiness" : "opportunity";

  let desk = await api<DeskResponse>("/desk", { as_of: sp.as_of, since_days: since, limit: 25, sort });
  let asOf = sp.as_of;
  let movedDate: string | null = null;

  // Land where the filings can support a view, rather than on an empty today.
  if (!sp.as_of && desk.data.coverage.suggested_as_of) {
    movedDate = fmt.date(desk.data.coverage.suggested_as_of);
    asOf = movedDate;
    desk = await api<DeskResponse>("/desk", { as_of: asOf, since_days: since, limit: 25, sort });
  }

  const { rows, coverage } = desk.data;
  const keep = asOf ? `as_of=${asOf}&` : "";
  const missing = [...new Set(rows.flatMap((r) => r.opportunity_missing))];

  return (
    <div className="grid gap-8">
      <header className="grid gap-3">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <h1 className="text-[28px]">List</h1>
          <p className="text-[13px] text-ink-3 m-0">
            {rows.length} of {coverage.covered_companies} covered companies changed in the last {since} days · as of{" "}
            <span className="num">{desk.as_of.slice(0, 10)}</span>
          </p>
          <div className="ml-auto">
            <Refresh builtAt={new Date().toISOString()} />
          </div>
        </div>
        <p className="prose text-ink-2 m-0">
          Ranked by opportunity: how much the fundamentals are changing, how far the accounts can be trusted, how cheap
          it is against its peers, and how little attention it gets, less what could go wrong. Open any company for the
          reasons in plain words and the filings underneath them.
        </p>
      </header>

      {movedDate && (
        <div className="card p-5 grid gap-2">
          <p className="text-[14px] m-0">
            <span className="text-caution">Showing {movedDate}, not today.</span>{" "}
            <span className="text-ink-2">
              Prices and announcements are current, but the exchange&apos;s results feed stops at the quarter ending{" "}
              <span className="num">{fmt.date(coverage.latest_fundamental_period_end)}</span>, so a view dated today
              would rank companies on filings {coverage.fundamentals_stale_days} days old.
            </span>
          </p>
          <p className="text-[13px] m-0">
            <Link href={`/?as_of=${new Date().toISOString().slice(0, 10)}&since=${since}`}>View today anyway</Link>
            <span className="text-ink-3"> · </span>
            <Link href="/data">Freshness by source</Link>
          </p>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="card p-6 grid gap-2">
          <h2 className="text-[18px]">Nothing to rank in this window</h2>
          <p className="text-[14px] text-ink-2 max-w-measure m-0">
            {coverage.covered_companies === 0 ? (
              <>
                No company has fundamentals loaded, so nothing can be assessed. Run{" "}
                <span className="num">scripts/sync_live.py</span> to ingest quarterly results.
              </>
            ) : (
              <>
                {coverage.covered_companies} companies have fundamentals loaded and none disclosed a change in the last{" "}
                {since} days.
                {coverage.latest_signal_at && (
                  <>
                    {" "}
                    The most recent change on file is from{" "}
                    <span className="num">{fmt.date(coverage.latest_signal_at)}</span>.
                  </>
                )}
              </>
            )}
          </p>
          {coverage.suggested_window_days && (
            <p className="text-[14px] m-0">
              <Link href={`/?${keep}since=${coverage.suggested_window_days}`}>
                Widen to {coverage.suggested_window_days} days
              </Link>
            </p>
          )}
        </div>
      ) : (
        <RankedList rows={rows} asOf={asOf} />
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-[12px] text-ink-3">
        <Link href={`/?${keep}sort=${sort === "opportunity" ? "readiness" : "opportunity"}&since=${since}`}>
          Sort by {sort === "opportunity" ? "readiness" : "opportunity"}
        </Link>
        <Link href={`/screener${asOf ? `?as_of=${asOf}` : ""}`}>Full universe and filters</Link>
        {missing.length > 0 && (
          <span className="max-w-measure">
            <span className="text-caution">*</span> Excludes {missing.join(" and ")}: the filings on file do not carry
            the data to measure it. A dash is an unmeasured factor, not a bad one.
          </span>
        )}
      </div>
    </div>
  );
}
