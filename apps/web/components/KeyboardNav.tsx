"use client";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

// g d / g s / g q jump between pages; j / k move the row cursor in the focused table; Enter opens.
export function KeyboardNav() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    let pendingG = false;
    const keep = params.get("as_of") ? `?as_of=${params.get("as_of")}` : "";
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (pendingG) {
        pendingG = false;
        if (e.key === "d") router.push(`/${keep}`);
        if (e.key === "s") router.push(`/signals${keep}`);
        if (e.key === "q") router.push(`/data${keep}`);
        return;
      }
      if (e.key === "g") { pendingG = true; return; }
      if (e.key === "j" || e.key === "k" || e.key === "Enter") {
        const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tr[data-href]"));
        if (!rows.length) return;
        const current = rows.findIndex((r) => r.dataset.selected === "true");
        if (e.key === "Enter") { const r = rows[Math.max(current, 0)]; if (r?.dataset.href) router.push(r.dataset.href); return; }
        const next = e.key === "j" ? Math.min(current + 1, rows.length - 1) : Math.max(current - 1, 0);
        rows.forEach((r, i) => (r.dataset.selected = String(i === next)));
        rows[next]?.scrollIntoView({ block: "nearest" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, params]);
  return null;
}
