import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import "./globals.css";
import { AsOfSelector } from "@/components/AsOfSelector";
import { KeyboardNav } from "@/components/KeyboardNav";

export const metadata: Metadata = { title: "SignalAlpha", description: "Research terminal for Indian small caps, public data only." };

const DISCLAIMER =
  "SignalAlpha uses public information only. Outputs may contain errors. Past signal performance is not indicative of future returns. Scores are research rankings; nothing here is investment advice.";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="flex items-center gap-6 px-4 py-2 border-b border-ink-600 bg-ink-800 sticky top-0 z-10">
          <Link href="/" className="text-slate-100 font-semibold no-underline">SignalAlpha</Link>
          <nav className="flex gap-4">
            <Link href="/">Desk <span className="kbd">g d</span></Link>
            <Link href="/journal">Journal <span className="kbd">g j</span></Link>
            <Link href="/screener">Screener <span className="kbd">g c</span></Link>
            <Link href="/signals">Signals <span className="kbd">g s</span></Link>
            <Link href="/data">Data <span className="kbd">g q</span></Link>
          </nav>
          <div className="ml-auto"><Suspense><AsOfSelector /></Suspense></div>
        </header>
        <Suspense><KeyboardNav /></Suspense>
        <main className="px-4 py-3">{children}</main>
        <footer className="px-4 py-3 text-[11px] text-muted border-t border-ink-600">{DISCLAIMER}</footer>
      </body>
    </html>
  );
}
