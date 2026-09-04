"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

// A research verdict, not a trade instruction: the vocabulary is about where attention goes,
// and a decision cannot be recorded without a reason, because the reason is the point.
const VERDICTS = [
  { key: "shortlist", label: "Shortlist", hint: "worth committing real work to" },
  { key: "track", label: "Track", hint: "interesting, not yet" },
  { key: "needs_evidence", label: "Needs evidence", hint: "blocked on a specific fact" },
  { key: "pass", label: "Pass", hint: "not pursuing" },
];

export function DecideForm({
  companyId,
  suggestedReviewBy,
  asOf,
  defaultTrigger,
}: {
  companyId: number;
  suggestedReviewBy: string;
  asOf?: string;
  defaultTrigger: string;
}) {
  const router = useRouter();
  const [verdict, setVerdict] = useState("track");
  const [reason, setReason] = useState("");
  const [conviction, setConviction] = useState("");
  const [trigger, setTrigger] = useState(defaultTrigger);
  const [reviewBy, setReviewBy] = useState(suggestedReviewBy.slice(0, 10));
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (reason.trim().length < 3) {
      setState("error");
      setMessage("Write one line on why. That is what you will read back later.");
      return;
    }
    setState("saving");
    const res = await fetch(`/api/companies/${companyId}/decisions${asOf ? `?as_of=${asOf}` : ""}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        verdict,
        reason,
        conviction: conviction || null,
        review_trigger: trigger || null,
        review_by: reviewBy || null,
        as_of: asOf ?? null,
      }),
    });
    if (!res.ok) {
      setState("error");
      setMessage(`Could not save: ${await res.text()}`);
      return;
    }
    setState("saved");
    setMessage("Recorded.");
    router.refresh();
  };

  const field = "mt-1 w-full bg-ground border border-rule rounded-md px-3 py-2 text-[14px] text-ink";
  return (
    <form onSubmit={submit} className="grid gap-4">
      <div className="flex flex-wrap gap-2">
        {VERDICTS.map((v) => (
          <button
            key={v.key}
            type="button"
            onClick={() => setVerdict(v.key)}
            title={v.hint}
            aria-pressed={verdict === v.key}
            className={`px-4 py-2 rounded-md border text-[14px] ${
              verdict === v.key ? "border-link text-link bg-raised" : "border-rule text-ink-2 hover:border-rule-strong"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>
      <label className="label block">
        Why
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="Margins look structural, but it takes two weeks to exit. One more quarter first."
          className={`${field} font-sans normal-case tracking-normal`}
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="label block">
          Tell me if this happens
          <input value={trigger} onChange={(e) => setTrigger(e.target.value)} className={`${field} font-sans normal-case tracking-normal`} />
        </label>
        <div className="grid grid-cols-2 gap-4">
          <label className="label block">
            Conviction
            <select value={conviction} onChange={(e) => setConviction(e.target.value)} className={`${field} font-sans normal-case tracking-normal`}>
              <option value="">unset</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label className="label block">
            Review by
            <input type="date" value={reviewBy} onChange={(e) => setReviewBy(e.target.value)} className={`${field} num`} />
          </label>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={state === "saving"}
          className="px-4 py-2 rounded-md border border-link text-link hover:bg-raised disabled:opacity-40 text-[14px]"
        >
          {state === "saving" ? "Saving" : "Record decision"}
        </button>
        {message && <span className={`text-[13px] ${state === "error" ? "text-neg" : "text-pos"}`}>{message}</span>}
      </div>
    </form>
  );
}
