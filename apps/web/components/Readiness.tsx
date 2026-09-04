import type { Readiness } from "@/lib/api";

const TONE: Record<string, string> = { ready: "text-pos border-pos", partial: "text-warn border-warn", not_ready: "text-neg border-neg" };
const WORD: Record<string, string> = { ready: "Ready to decide", partial: "Decidable, with gaps", not_ready: "Not ready" };

export function ReadinessBadge({ readiness }: { readiness: Readiness }) {
  return <span className={`pill ${TONE[readiness.status]}`} style={{ borderColor: "currentColor" }}>{WORD[readiness.status]}</span>;
}

// The checklist names what is missing, so the reader knows what to go and get.
export function ReadinessList({ readiness }: { readiness: Readiness }) {
  return (
    <ul className="space-y-1 text-[12px]">
      {readiness.checks.map((c) => (
        <li key={c.key} className="flex gap-2">
          <span className={c.passed ? "text-pos" : c.critical ? "text-neg" : "text-warn"} aria-hidden>{c.passed ? "✓" : c.critical ? "✗" : "!"}</span>
          <span>
            <span className={c.passed ? "" : "text-slate-100"}>{c.label}.</span>{" "}
            <span className="text-muted">{c.detail}</span>
            {!c.passed && c.to_resolve && <span className="block text-warn">→ {c.to_resolve}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
