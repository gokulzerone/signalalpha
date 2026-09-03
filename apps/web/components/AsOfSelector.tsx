"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// View any page as it would have looked on a past date (PRD §12.2 header).
export function AsOfSelector() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const value = params.get("as_of") ?? "";
  return (
    <label className="text-muted text-[11px] flex items-center gap-2">
      as of
      <input
        type="date"
        value={value}
        onChange={(e) => {
          const next = new URLSearchParams(params.toString());
          if (e.target.value) next.set("as_of", e.target.value);
          else next.delete("as_of");
          router.push(`${pathname}?${next.toString()}`);
        }}
        className="bg-ink-700 border border-ink-500 rounded px-1 text-slate-200"
      />
      {value && <button className="kbd" onClick={() => { const next = new URLSearchParams(params.toString()); next.delete("as_of"); router.push(`${pathname}?${next.toString()}`); }}>latest</button>}
    </label>
  );
}
