"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

// Records a research verdict. Deliberately not a trade instruction: the vocabulary is about
// where the reader's attention goes, and every decision has to carry a reason.
const VERDICTS = [
  { key: "shortlist", label: "Shortlist", hint: "worth committing real work to" },
  { key: "track", label: "Track", hint: "interesting, not yet" },
  { key: "needs_evidence", label: "Needs evidence", hint: "blocked on a specific fact" },
  { key: "pass", label: "Pass", hint: "not pursuing" },
];

export function DecideForm({ companyId, suggestedReviewBy, asOf, defaultTrigger }: { companyId: number; suggestedReviewBy: string; asOf?: string; defaultTrigger: string }) {
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
    if (reason.trim().length < 3) { setState("error"); setMessage("Write one line on why. The record is the point."); return; }
    setState("saving");
    const res = await fetch(`/api/companies/${companyId}/decisions${asOf ? `?as_of=${asOf}` : ""}`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ verdict, reason, conviction: conviction || null, review_trigger: trigger || null, review_by: reviewBy || null, as_of: asOf ?? null }),
    });
    if (!res.ok) { setState("error"); setMessage(`Could not save: ${await res.text()}`); return; }
    setState("saved"); setMessage("Recorded.");
    router.refresh();
  };

  return (
    <form onSubmit={submit} className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        {VERDICTS.map((v) => (
          <button key={v.key} type="button" onClick={() => setVerdict(v.key)} title={v.hint}
            className={`px-3 py-1 rounded border text-[12px] ${verdict === v.key ? "border-accent text-accent bg-panel2" : "border-rule text-muted"}`}>
            {v.label}
          </button>
        ))}
      </div>
      <label className="text-[11px] text-muted">Why (this is what you will read back later)
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="e.g. Margin gain looks structural, but I want one more quarter before sizing up."
          className="mt-1 w-full bg-panel border border-rule rounded px-2 py-1 text-[13px] text-slate-200" />
      </label>
      <div className="flex flex-wrap gap-4">
        <label className="text-[11px] text-muted">Conviction
          <select value={conviction} onChange={(e) => setConviction(e.target.value)} className="ml-2 bg-panel border border-rule rounded px-1 text-slate-200">
            <option value="">unset</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option>
          </select>
        </label>
        <label className="text-[11px] text-muted">Review by
          <input type="date" value={reviewBy} onChange={(e) => setReviewBy(e.target.value)} className="ml-2 bg-panel border border-rule rounded px-1 text-slate-200" />
        </label>
      </div>
      <label className="text-[11px] text-muted">Tell me if this happens
        <input value={trigger} onChange={(e) => setTrigger(e.target.value)} className="mt-1 w-full bg-panel border border-rule rounded px-2 py-1 text-[13px] text-slate-200" />
      </label>
      <div className="flex items-center gap-3">
        <button type="submit" disabled={state === "saving"} className="px-3 py-1 rounded border border-accent text-accent text-[12px] disabled:opacity-50">
          {state === "saving" ? "Saving…" : "Record decision"}
        </button>
        {message && <span className={state === "error" ? "text-neg text-[12px]" : "text-pos text-[12px]"}>{message}</span>}
      </div>
    </form>
  );
}
