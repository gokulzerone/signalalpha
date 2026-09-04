import { api, type Capabilities } from "@/lib/api";
import { InvestigationPanel } from "@/components/Investigation";

// Investigate works from the outside in, so the page opens by saying so and offering one
// action. Nothing moves until the user starts a run, and then the words on screen follow the
// worker rather than a timer.
export default async function InvestigatePage({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const { as_of } = await searchParams;
  const caps = await api<Capabilities>("/investigations/capabilities", { as_of });
  // Run against a date whose filings are still current, so the investigation settles on a
  // company it can actually say something about.
  const effective = as_of ?? caps.data.suggested_as_of?.slice(0, 10);
  return (
    <div className="grid gap-8">
      <header className="grid gap-2">
        <h1 className="text-[28px]">Investigate</h1>
        <p className="text-[13px] text-ink-3 m-0">
          From world conditions down to one listed Indian company
        </p>
      </header>
      {!as_of && caps.data.suggested_as_of && (
        <p className="text-[13px] text-ink-2 max-w-measure m-0">
          This will run as of{" "}
          <span className="num">{caps.data.suggested_as_of.slice(0, 10)}</span>, the most recent date whose filings are
          still current. Dated today it would settle on a company whose last reported quarter is far behind.
        </p>
      )}
      <InvestigationPanel capabilities={caps.data} asOf={effective} />
    </div>
  );
}
