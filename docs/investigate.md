# Investigate

The list starts from the companies this system already covers and ranks them. Investigate runs
the other way, the way a macro-led investor works: what is happening in the world, what those
conditions change, where supply and demand move, and only then which listed Indian company
stands in the path of it.

## The nine steps

| | Step | Reads |
|---|---|---|
| 1 | Scanning the world for economic conditions | the open web |
| 2 | Working out what those conditions change | the open web |
| 3 | Tracing the effect on supply and demand | the open web |
| 4 | Scanning India for companies in the path of it | our universe |
| 5 | Finalising the company | our scores |
| 6 | Checking what the market is paying for it | prices and filings |
| 7 | Reading its filings | filings |
| 8 | Looking for what could go wrong | signals, flags, liquidity |
| 9 | Writing up why it is worth the work | all of the above |

The page shows the present-tense line while a step is working and what it found once it is
done. Progress is read from the row the worker is writing, so a line only changes when a step
has actually finished. Nothing is on a timer.

## Two rules that keep it honest

**The web narrows, the filings decide.** Steps 1 to 3 read the open web, and every claim they
make carries the page it came from. That material only ever narrows *which* companies to look
at. What is then said about a company comes from filings already ingested here, with the
numbers computed in Python. Web material never becomes evidence in the PRD §8 sense and is
never mixed into the filing-derived record.

**A company is never invented.** Step 4 matches the sectors the macro reading named against the
companies this system actually covers, and step 5 picks from that shortlist. If the web named
sectors nobody here covers, the step says so and considers every covered company instead,
rather than reaching for a name it cannot support.

## Without a Claude API key

The first three steps need one. Without it they are marked skipped, each saying exactly what
to set, and the investigation runs from step 4 using the filings already loaded. That is a
narrower run and the page says so; it is not a simulation of the missing steps.

```bash
export ANTHROPIC_API_KEY=...
export SIGNALALPHA_LLM_PROVIDER=anthropic
```

Set on the API and the worker. The macro steps then use Claude with Anthropic's server-side
web search, and the pages read are listed under each step.

## Dates

An investigation dated after the newest filings on file would settle on a company it cannot say
anything current about, so the page runs as of the most recent date whose filings are still
current and says which date that is. Pick any other date with the control in the header.
