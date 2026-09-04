# The decision layer

The research modules answer *what changed and is it true*. They do not answer *so what do I
do*, which is why a dashboard of forty scored rows leaves a reader stuck. This layer closes
that gap without ever telling anyone to trade: the vocabulary is about where research
attention goes, and the words buy, sell, target price and recommendation appear nowhere in
its output (PRD §16, enforced by a test).

## The flow

**1. The desk (`/`)** replaces the wall of rows with a short queue. Each card carries one
plain sentence about what changed, the strongest point for and against, what signals of that
kind did historically, and a badge saying whether the research is complete enough to form a
view. Cards that are not decidable are separated out and each says what it is waiting for.

**2. The brief (`/companies/{id}/brief`)** runs in the order a person actually decides:

| Step | Question |
|---|---|
| 1 | What changed? |
| 2 | Is it true? (every line opens the filing) |
| 3 | Can the business be trusted? (quality, risk, forensic flags) |
| 4 | What does the price already assume? |
| 5 | What is the case against? |
| 6 | What happened last time signals like this fired? |
| 7 | How much could you even trade, and how long to get out? |
| 8 | What would change your mind? |
| 9 | Where the research stands (the readiness checklist) |
| 10 | Your decision |

**3. The decision** is recorded with a required reason, an optional conviction, a review date
and a trigger in the reader's own words. The scores, signal ids and readiness at that moment
are stored alongside it, so the record can be audited later against what was actually known.

**4. The journal (`/journal`)** lists every decision and raises an alert when a name that was
kept throws a negative signal, or when a review comes due.

## Why a checklist instead of a score

A single "confidence" number hides which part is missing. `decisions/readiness.py` runs named
checks (financials current, enough history to compare, claims trace to filings, case against
written, tradeable size, history of this signal type, accounting flags, source completeness)
and each failure carries the one thing that would fix it: *load two more quarters*, *wait for
results after 31 Dec 2024*, *run the research job so the case against is written*. Critical
failures block a "ready" verdict; the rest downgrade it to "decidable, with gaps".

## Plain language, from the detector's own numbers

`decisions/narrate.py` renders every one of the thirty signal types as a sentence built from
the parameters the Python detector computed, with no model involved: *"Revenue grew 34% year
on year, 18pp faster than its average of the previous four quarters."* If a parameter is
missing the sentence degrades to the definition rather than inventing a figure.

## Liquidity arithmetic, not advice

`decisions/sizing.py` answers how many trading days a given position would take to exit at a
stated participation rate, and what the round trip costs. It never suggests a position size;
it shows the constraint and leaves the number to the reader.
