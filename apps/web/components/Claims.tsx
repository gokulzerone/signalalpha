import Link from "next/link";
import type { Claim, Evidence } from "@/lib/api";

// Every claim is a link to its evidence span in the source document (PRD §12.2.8).
export function Claims({ claims, evidence, companyId, asOf }: { claims: Claim[]; evidence: Map<number, Evidence>; companyId: number; asOf?: string }) {
  const q = asOf ? `&as_of=${asOf}` : "";
  return (
    <ul className="space-y-1 text-[12px]">
      {claims.map((c, i) => (
        <li key={i}>
          {c.text}{" "}
          {c.evidence_ids.map((eid) => {
            const ev = evidence.get(eid);
            const href = `/companies/${companyId}/documents/${ev?.raw_document_id ?? ""}?highlight=${eid}${q}`;
            return <Link key={eid} href={href} className="kbd no-underline mr-1" title={ev?.extracted_text ?? ""}>ev {eid}</Link>;
          })}
        </li>
      ))}
    </ul>
  );
}
