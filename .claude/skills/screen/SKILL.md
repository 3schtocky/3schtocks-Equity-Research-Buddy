---
name: screen
description: Screen US-listed stocks with Ethan and shortlist initiation candidates. Runs the quant screen (value, quality, growth, momentum), walks Ethan through the top names with AskUserQuestion, writes one-page pitch memos for his shortlist, and hands the chosen name to the initiate skill. Use when Ethan says "let's screen", "find ideas", "what should we cover next", or asks about screen results.
---

# Screen

Read `CLAUDE.md` first. Screens live in `coverage/_screens/<date>/` (screen.md, screen.csv, memos/).

## 1. Set up the run (ask, don't assume)
Ask Ethan with AskUserQuestion (one call, up to 4 questions):
- **Size floor:** $2 bn (default) / $10 bn (large caps, Owl-like) / $500 mn (include small caps).
- **Factor tilt:** balanced 30/30/20/20 (default) / value-heavy 45/30/10/15 / quality-growth 15/40/30/15 / momentum 20/20/20/40.
- **Sectors to exclude** (multi-select): none / Financials & REITs / Health Care (binary biotech outcomes) / Energy & Mining.
- **Already-covered names:** skip tickers that have a `coverage/<TICKER>/` folder with an initiation, or include them.

Then run `uv run erb screen --min-cap <bn> --weights <v,q,g,m>` (first run of the day takes ~6–8 minutes: it downloads a year of prices for ~7,000 tickers; later runs use the cache).

## 2. Review the results critically before showing Ethan
Read `screen.md`, then open `screen.csv` for the top ~40 and sanity-check each name before recommending it:
- One-off revenue spikes (a biotech's milestone year, an insurer's catastrophe-free year) inflate growth and quality; say so.
- Recent IPOs and spin-offs have thin history; check `factors_used` and `data_source`.
- Foreign 20-F filers have no value factor (currency); their rank rests on quality, growth and momentum.
- Momentum names near 52-week highs (`pct_off_high` near 0) vs value names that have fallen sharply.
- Apply the exclusions Ethan chose.

Summarize the screen in a few lines (sector mix, what the top is dominated by), then ask Ethan to pick a shortlist with AskUserQuestion using `multiSelect: true`: up to 4 questions of 4 names each (16 names), grouped by theme or sector. For each option, the description gives the one-line reason it screened (e.g. "Quality 0.95, growth 0.90; op margin 43.6%, 12-1m +81.5%").

## 3. Pitch memos for the shortlist
For each chosen ticker:
1. `uv run erb memo TICKER` (facts pack, draft model and the memo skeleton with numbers filled in).
2. A short research pass: the latest earnings release (in `coverage/<TICKER>/facts/`, or pull it with `erb facts TICKER`), plus 1–3 web searches for the biggest recent event. Log sources in the memo's Sources list.
3. Fill every `[VERIFY: write ...]` section: why it screened (and whether that is durable), the 2–3 sentence pitch, the biggest risks, and the questions an initiation would answer. Keep each memo to one page. Same guardrails as reports: every figure sourced, no em dashes, the draft model's rating described as a draft.

## 4. Pick the name
Give a compact comparison (one line per memo: pitch, draft rating and base PT, the main risk), then ask Ethan with AskUserQuestion which name to initiate on, with your recommendation first and marked "(Recommended)". Hand the chosen ticker to the `initiate` skill (stage 1). The memo is the seed of the research brief; reuse its sources.
