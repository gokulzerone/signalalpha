# UI (build step 9)

`apps/web` is a Next.js App Router application (TypeScript, Tailwind, Recharts) in a dark
research-terminal style. Server components fetch from the API with the server-held key;
client components (score hover cards, filters, the scenario editor) go through the
`/api/[...path]` proxy route so the key never reaches the browser.

| Route | PRD | Notes |
|---|---|---|
| `/` | §12.1 | Today's inflections and Red flags, one row per company with the six scores, key change, strongest positive/negative and a data-quality indicator. Filters live in the URL. Columns sort on click; score cells show their component table on hover. |
| `/companies/{id}` | §12.2 | The ten sections in PRD order. The as-of selector in the header re-renders the page as it looked on that date. Valuation scenarios recompute client-side with the formula spec served by the API. Thesis and contradiction are side by side and every claim links to its evidence. |
| `/companies/{id}/documents/{docId}?highlight=` | §8.2 | The stored document text, page by page, with the cited span highlighted and scrolled into view. |
| `/signals` | §12.3 | Backtest statistics per signal type and horizon with decay charts; rows with fewer than 30 events are greyed and flagged. |
| `/data` | §12.4 | Per-source freshness and failure counts, and per-company coverage gaps. |

Keyboard: `g d` / `g s` / `g q` switch pages; `j` / `k` move the row cursor; `Enter` opens
the selected company.

## Running locally without Docker

The dev and start scripts serve the app directly; the container image sets
`NEXT_STANDALONE=1` so the build emits a self-contained server instead.

```bash
make bootstrap   # embedded PostgreSQL under ~/.signalalpha, mock universe, signals, scores, backtest, agents
make api         # http://localhost:8000
make web         # http://localhost:3000
```

The persistent disclaimer in the footer and the absence of the words buy, sell, target
price and recommendation follow PRD §16.
