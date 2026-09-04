# Interface

`apps/web` is a Next.js App Router application. The design follows Rams and the Apple HIG in
one specific sense that matters for this product: **the interface must never make a figure
look more certain than it is.** That is not a style choice here, it is the same rule the data
layer enforces, carried through to the screen.

## The system

**Colour is achromatic.** The interface uses only paper, ink and rules. The single exception
is measured meaning: green for a good measured value, red for a bad one, amber for caution,
and one ink-blue for interaction. Nothing is tinted for decoration, so any colour on screen
can be read as information. An unmeasured value is grey, never red.

**Three type roles, each earning its place.** Archivo carries structure and labels; Source
Serif 4 carries the plain-language verdict, so the human-readable answer is visually distinct
from the machinery around it; IBM Plex Mono with tabular figures carries every number, so
columns align and a change of digit never shifts the layout.

**One dominant element per screen.** On the list it is the opportunity score; on a company it
is the verdict paragraph. Everything else is a step down in size and weight.

## Pages

| Route | What it answers |
|---|---|
| `/` | Which companies deserve my time, ranked, with what changed in one sentence each |
| `/companies/{id}` | Why, in plain words, then how it scores, then the filings underneath |
| `/companies/{id}/research` | Every figure, chart and table for the company |
| `/companies/{id}/documents/{docId}` | The filing itself, with the cited passage highlighted |
| `/journal` | What you decided, and what has happened since |
| `/screener` | The unfiltered universe with filters |
| `/signals`, `/data` | Backtest statistics, and freshness per source |

## The company page discloses in layers

A reader can stop at any layer and still have been told the truth, including what could not
be measured.

1. **The short version.** One paragraph in plain words: how many of the checkable measures
   look strong, what changed, how it is priced, how closely it is followed, and the risk.
   Then the caveats, each naming a real gap.
2. **How it scores.** Five factors, each with its score, a bar drawn on the full 0-100 scale,
   what that score means in words, and what the factor was measuring. Opening a row shows the
   components the score was built from.
3. **What changed.** Every signal as a sentence, each opening the filing it came from.
4. **The case against, what history says, what it would take to act, your decision.**
5. **Everything underneath**, one link away.

`decisions/verdict.py` composes the plain reading deterministically from measured values. An
unmeasured factor is stated as unmeasured rather than dropped, because a reader must never be
able to mistake "nobody could check this" for "we checked and it was fine". Caveats are tagged
with the concern they raise and de-duplicated, since the same gap reaching the reader in two
wordings reads as two problems.

## Running locally

```bash
make bootstrap   # embedded PostgreSQL, mock universe, signals, scores, backtest, agents
make api         # http://localhost:8000
make web         # http://localhost:3000
```

The dev and start scripts serve the app directly; the container image sets `NEXT_STANDALONE=1`
so the build emits a self-contained server instead.
