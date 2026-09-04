export const fmt = {
  num: (v: number | string | null | undefined, digits = 2): string => {
    if (v === null || v === undefined || v === "") return "–";
    const n = typeof v === "string" ? Number(v) : v;
    if (!Number.isFinite(n)) return "–";
    return n.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  },
  pct: (v: number | null | undefined, digits = 1): string => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`),
  score: (v: number | null | undefined): string => (v === null || v === undefined ? "–" : String(Math.round(v))),
  date: (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : "–"),
  cr: (v: number | string | null | undefined): string => (v === null || v === undefined ? "–" : `₹${fmt.num(v, 0)} cr`),
  rupees: (v: number | null | undefined): string =>
    v === null || v === undefined ? "–" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`,
  // A plain-English day count reads better than "0.4" when the answer is "immediately".
  days: (v: number | null | undefined): string =>
    v === null || v === undefined || !Number.isFinite(v) ? "–" : v < 1 ? "under a day" : `${v.toFixed(v < 10 ? 1 : 0)} days`,
};

// Colour is reserved for measured meaning. An unmeasured value is grey, never red.
export function scoreTone(scoreType: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-ink-3";
  const good = scoreType === "risk" ? v < 40 : v >= 60;
  const bad = scoreType === "risk" ? v >= 70 : v < 30;
  return good ? "text-pos" : bad ? "text-neg" : "text-ink";
}
