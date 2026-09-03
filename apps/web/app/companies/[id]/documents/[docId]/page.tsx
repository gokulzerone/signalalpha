import Link from "next/link";
import { api, type DocumentOut } from "@/lib/api";
import { fmt } from "@/lib/format";

// Renders the original document text with the cited span highlighted (PRD §8.2 rule 4).
export default async function DocumentPage({ params, searchParams }: { params: Promise<{ id: string; docId: string }>; searchParams: Promise<{ highlight?: string; as_of?: string }> }) {
  const { id, docId } = await params;
  const { highlight, as_of } = await searchParams;
  const doc = await api<DocumentOut>(`/companies/${id}/documents/${docId}`, { highlight, as_of });
  const d = doc.data;
  const h = d.highlight;
  const pages = d.text.split("\f");
  let offset = 0;
  return (
    <div className="space-y-3">
      <div className="text-muted text-[11px]"><Link href={`/companies/${id}${as_of ? `?as_of=${as_of}` : ""}`}>← company</Link> · {d.source} · public {fmt.date(d.public_at)} · document {d.raw_document_id}{h ? ` · evidence ${h.evidence_id} on page ${h.page_number}` : ""}</div>
      <h1 className="text-slate-100">{d.title ?? `Document ${d.raw_document_id}`}</h1>
      {pages.map((page, i) => {
        const start = offset;
        offset += page.length + 1;
        const inPage = h && h.char_start >= start && h.char_start < start + page.length;
        return (
          <div key={i} className="card">
            <div className="text-muted text-[10px] mb-1">page {i + 1}</div>
            <pre className="whitespace-pre-wrap text-[12px]">
              {inPage && h ? (
                <>
                  {page.slice(0, h.char_start - start)}
                  <mark id="highlight">{page.slice(h.char_start - start, h.char_end - start)}</mark>
                  {page.slice(h.char_end - start)}
                </>
              ) : page}
            </pre>
          </div>
        );
      })}
      {h && <script dangerouslySetInnerHTML={{ __html: "document.getElementById('highlight')?.scrollIntoView({block:'center'});" }} />}
    </div>
  );
}
