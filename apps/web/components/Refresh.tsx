"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

// Re-fetches the list from the API. Ingesting new filings is a separate job
// (scripts/sync_live.py); this picks up whatever has landed since the page was rendered.
export function Refresh({ builtAt }: { builtAt: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [at, setAt] = useState(builtAt);
  return (
    <span className="flex items-center gap-2 text-[11px] text-muted">
      <button
        onClick={() => start(() => { router.refresh(); setAt(new Date().toISOString()); })}
        disabled={pending}
        className="px-2 py-[3px] border border-rule rounded text-slate-200 hover:border-accent hover:text-accent disabled:opacity-50"
      >
        {pending ? "Refreshing…" : "Refresh"}
      </button>
      <span>loaded {at.slice(11, 16)}</span>
    </span>
  );
}
