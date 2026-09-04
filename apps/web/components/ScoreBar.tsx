import { fmt, scoreTone } from "@/lib/format";

// A percentile drawn to its own scale: the track is the full 0-100 range, so a short bar and
// a dash are visibly different things.
export function ScoreBar({
  value,
  scoreType,
  width = 96,
}: {
  value: number | null | undefined;
  scoreType: string;
  width?: number;
}) {
  const measured = value !== null && value !== undefined;
  const pctValue = measured ? Math.max(0, Math.min(100, value)) : 0;
  return (
    <span className="inline-flex items-center gap-3">
      <span className={`num text-[15px] w-8 text-right ${scoreTone(scoreType, value)}`}>{fmt.score(value)}</span>
      <span
        className="relative block h-[3px] rounded-full bg-bar"
        style={{ width }}
        role="img"
        aria-label={measured ? `${Math.round(pctValue)} out of 100` : "not measured"}
      >
        {measured && (
          <span
            className={`absolute left-0 top-0 h-full rounded-full ${scoreTone(scoreType, value).replace("text-", "bg-")}`}
            style={{ width: `${pctValue}%` }}
          />
        )}
      </span>
    </span>
  );
}
