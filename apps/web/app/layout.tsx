import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import "./globals.css";
import { AsOfSelector } from "@/components/AsOfSelector";

export const metadata: Metadata = {
  title: "SignalAlpha",
  description: "Fundamental changes at Indian small caps, from exchange filings only.",
};

// Two places to be: the ranked list, and a run that works from the world inwards.
const NAV = [
  ["/", "List"],
  ["/investigate", "Investigate"],
];

// The chrome defers to the content: one hairline, one row, no colour.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap"
        />
      </head>
      <body>
        <header className="hairline bg-surface">
          <div className="mx-auto max-w-[1120px] px-6 h-14 flex items-center gap-8">
            <Link href="/" className="text-ink no-underline hover:no-underline font-semibold tracking-tight">
              SignalAlpha
            </Link>
            <nav className="flex gap-6 text-[14px]">
              {NAV.map(([href, label]) => (
                <Link key={href} href={href} className="text-ink-2 no-underline hover:text-ink hover:no-underline">
                  {label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto">
              <Suspense>
                <AsOfSelector />
              </Suspense>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1120px] px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-[1120px] px-6 pb-16 pt-8">
          <p className="text-[12px] text-ink-3 max-w-measure m-0">
            Research from public filings only. Figures may contain errors, past signal performance is not indicative of
            future returns, and nothing here is investment advice.
          </p>
        </footer>
      </body>
    </html>
  );
}
