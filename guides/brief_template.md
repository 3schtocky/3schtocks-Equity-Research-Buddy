# Research Brief Template (`coverage/<TICKER>/brief.md`)

The brief is the facts pack Ethan reviews **before** any modeling or writing. It is
research notes, not prose: dense bullets, every figure tagged `[Sn]` (or `[F]` for
figures taken straight from `facts/facts.md`, which carries its own sources).
Aim for 2–4 pages. Mark anything uncertain `[VERIFY: ...]`.

```markdown
# <Company> (<TICKER>): Research Brief
Prepared <date> · Price <$> (<as-of> close) · Market cap <$> · Draft rating: none yet

## 1. Snapshot
- What it does in one line; segments with % of last FY revenue [F]
- Scale: revenue, EBITDA margin, FCF, net cash/debt, employees [F]
- Stock: YTD / 1-year return, 52-week range, NTM P/E vs 1/2/3-year medians [F]

## 2. How it makes money
- Per segment: products, customers, pricing mechanism, KPIs and their recent trend [Sn]
- Geographic mix and currency exposure [F]/[Sn]

## 3. Industry
- Market size and growth (TAM, CAGR, source + year) [Sn]
- 3–5 structural trends that matter for this name [Sn]
- Competitive position and share [Sn]

## 4. What happened to the stock (event timeline, last 12–24 months)
| Date | Event | Stock / multiple reaction | Source |
One row per earnings print, guidance change, M&A, regulatory event, competitor news, macro shock.

## 5. The Street
- Consensus revenue / EPS for FY1 and FY2, revisions trend, Street PT range and rating mix [F]
- The 2–3 debates the Street is having (bull vs bear points) [Sn]

## 6. Candidate thesis pillars (2–4)
For each: the claim, the evidence, what the Street is missing, and how it shows up in numbers.

## 7. Candidate catalysts (dated) and risks (with mitigants)

## 8. Proposed peer set (4–6 tickers) with a one-line reason each

## 9. Model starting points
- Draft assumptions from `erb model --init` summary and what we would change and why
- Guidance to anchor on (CapEx, margins, growth) [Sn]

## 10. Questions for Ethan
- Holdings disclosure (does the author own the stock?)
- Which thesis pillars to pursue; peer set OK?; any angle to emphasize or avoid
```

## sources.md format
One line per source, numbered in order of first use. No em dashes.
```
- [S1] Meta Platforms 10-K for FY2025 (filed 2026-01-29): https://www.sec.gov/... (accessed 2026-09-29)
- [S2] Statista, "Digital advertising spending worldwide 2021-2027" (2026): https://... (accessed 2026-09-29)
```
Prefer primary sources (filings, company IR, government and industry-body data). For press
or research-firm figures, name the publisher and the date of the figure. Figures from
`facts/facts.md` may be cited as `[F]` in the brief; in `sections/*.md` cite the underlying
filing as an `[Sn]` (the facts pack lists the filing URLs) or `[M]` if the figure comes from
the model.
