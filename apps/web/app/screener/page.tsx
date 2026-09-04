import { api, type CompanyRow, type Page } from "@/lib/api";
import { CompanyTable } from "@/components/CompanyTable";
import { Filters } from "@/components/Filters";
import { Suspense } from "react";

type Search = Record<string, string | undefined>;

export default async function Screener({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const since = `${sp.since ?? "7"}d`;
  const common = { as_of: sp.as_of, page_size: 200 };
  const [inflections, redFlags] = await Promise.all([
    api<Page<CompanyRow>>("/discoveries/inflections", { since, ...common }),
    api<Page<CompanyRow>>("/discoveries/red-flags", { since, ...common }),
  ]);
  const passes = (r: CompanyRow) => {
    const s = r.scores;
    const num = (k: string) => (sp[k] ? Number(sp[k]) : undefined);
    if (sp.sector && r.sector !== sp.sector) return false;
    if (num("market_cap_min") !== undefined && (r.market_cap_cr ?? -1) < num("market_cap_min")!) return false;
    if (num("market_cap_max") !== undefined && (r.market_cap_cr ?? Infinity) > num("market_cap_max")!) return false;
    if (num("opportunity_min") !== undefined && (s.opportunity ?? -1) < num("opportunity_min")!) return false;
    if (num("risk_max") !== undefined && (s.risk ?? Infinity) > num("risk_max")!) return false;
    if (num("attention_gap_min") !== undefined && (s.attention_gap ?? -1) < num("attention_gap_min")!) return false;
    if (sp.signal_type && !r.new_signal_types.includes(sp.signal_type)) return false;
    if (sp.exclude_illiquid === "true" && r.is_illiquid) return false;
    const under = Boolean(r.gsm_stage || r.asm_stage);
    if (sp.surveillance === "true" && !under) return false;
    if (sp.surveillance === "false" && under) return false;
    return true;
  };
  return (
    <div className="space-y-6">
      <div className="note">The full universe, unfiltered. Use the <a href="/">desk</a> when you want a short queue to act on. As of {inflections.as_of.slice(0, 10)} · dataset {inflections.dataset} · window {since}. <span className="kbd">j</span>/<span className="kbd">k</span> move, <span className="kbd">Enter</span> open</div>
      <Suspense><Filters /></Suspense>
      <section>
        <h2 className="text-slate-100 mb-2">Today&apos;s inflections <span className="text-muted">({inflections.data.total})</span></h2>
        <Suspense><CompanyTable rows={inflections.data.items.filter(passes)} /></Suspense>
      </section>
      <section>
        <h2 className="text-slate-100 mb-2">Red flags <span className="text-muted">({redFlags.data.total})</span></h2>
        <Suspense><CompanyTable rows={redFlags.data.items.filter(passes)} defaultSort="risk" /></Suspense>
      </section>
    </div>
  );
}
