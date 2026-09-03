export const fmt = {
  num: (v: number | string | null | undefined, digits = 2): string => {
    if (v === null || v === undefined || v === "") return "–";
    const n = typeof v === "string" ? Number(v) : v;
    if (!Number.isFinite(n)) return "–";
    return n.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  },
  pct: (v: number | null | undefined, digits = 1): string => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`),
  score: (v: number | null | undefined): string => (v === null || v === undefined ? "–" : v.toFixed(0)),
  date: (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : "–"),
  cr: (v: number | string | null | undefined): string => (v === null || v === undefined ? "–" : `₹${fmt.num(v, 0)} cr`),
};

export function scoreTone(score_type: string, v: number | null): string {
  if (v === null) return "text-muted";
  const good = score_type === "risk" ? v < 40 : v >= 60;
  const bad = score_type === "risk" ? v >= 70 : v < 30;
  return good ? "text-pos" : bad ? "text-neg" : "text-warn";
}
