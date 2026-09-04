"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// Any page can be read as it stood on a past date. Unobtrusive by default: a bare date field
// with no label until it holds a value.
export function AsOfSelector() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const value = params.get("as_of") ?? "";
  const set = (v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set("as_of", v);
    else next.delete("as_of");
    router.push(`${pathname}?${next.toString()}`);
  };
  return (
    <div className="flex items-center gap-2 text-[13px] text-ink-3">
      <label htmlFor="asof">As of</label>
      <input
        id="asof"
        type="date"
        value={value}
        onChange={(e) => set(e.target.value)}
        className="bg-surface border border-rule rounded-md px-2 py-1 text-ink num"
      />
      {value && (
        <button onClick={() => set("")} className="text-link hover:underline">
          latest
        </button>
      )}
    </div>
  );
}
