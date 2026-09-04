# The decision layer

The research modules answer *what changed and is it true*. They do not answer *so what do I
do*, which is why a dashboard of forty scored rows leaves a reader stuck. This layer closes
that gap without ever telling anyone to trade: the vocabulary is about where research
attention goes, and the words buy, sell, target price and recommendation appear nowhere in
its output (PRD §16, enforced by a test).

## The flow

**1. The list (`/`)** is a ranked answer to "which of these deserves my time". It sorts by
Opportunity, puts the rank, the company, the composite score and the one-sentence change
first and largest, and keeps the component scores, readiness and base rate as supporting
detail. It opens on a date the data can actually support rather than on an empty today, has
a refresh control, and every row opens the full reasoning.

The older grouped queue is still there behind "sort by readiness". The original description
of it: it replaces the wall of rows with a short queue. Each card carries one
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

## When a source is missing

Live coverage is uneven: prices exist for every listed company, fundamentals for the ones
whose filings have been fetched, and ownership or annual-report data for none of them yet.
Rather than fail, an agent whose source is absent records a completed run whose output is
`{"status": "no_data", "reason": ...}`. The Contradiction agent then reads whatever work
exists and says in its own case which part could not be assessed, and the readiness
checklist names the same gap in the reader's language. The single hard dependency from the
PRD survives untouched: there is no thesis without a contradiction.

## Measured zero versus unmeasurable

The Opportunity composite is multiplicative, so a component measured as zero collapses it.
That is deliberate. A component that could not be *measured at all* is a different thing: the
mean is taken over the components that exist, the result is flagged `partial` with the
missing ones named, and the reader is told that a dash is an unmeasured component rather than
a bad one, and that a partial score is not comparable with a complete one.

This matters on live data. Quality reads return on capital, cash conversion, receivable days
and promoter holding, none of which appear in an Indian quarterly filing. Treating that as a
zero scored every real company at zero and made the ranking useless while looking confident.
