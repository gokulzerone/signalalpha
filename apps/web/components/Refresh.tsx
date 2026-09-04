"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

// Re-reads the list from the API. Ingesting new filings is a separate job, so this picks up
// whatever has landed since the page was rendered.
export function Refresh({ builtAt }: { builtAt: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [at, setAt] = useState(builtAt);
  return (
    <span className="flex items-center gap-3 text-[12px] text-ink-3">
      <span className="num">{at.slice(11, 16)}</span>
      <button
        onClick={() =>
          start(() => {
            router.refresh();
            setAt(new Date().toISOString());
          })
        }
        disabled={pending}
        className="border border-rule rounded-md px-3 py-1 text-ink-2 hover:text-ink hover:border-rule-strong disabled:opacity-40"
      >
        {pending ? "Refreshing" : "Refresh"}
      </button>
    </span>
  );
}
