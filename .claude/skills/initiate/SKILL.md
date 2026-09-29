---
name: initiate
description: Write a Conscious Investments initiating coverage report on a ticker, from SEC filings and web research through the research brief (stop for Ethan's review), the valuation model, the written sections and the finished .docx/.pdf. Use when Ethan says "initiate on X", "start coverage of X", "write the report on X", or asks to continue an initiation in progress.
---

# Initiate Coverage

Work product lives in `coverage/<TICKER>/`. Read `CLAUDE.md` first; its guardrails override anything here.
Track progress in `coverage/<TICKER>/STATUS.md` (create it at stage 1, update it at the end of every stage)
so a later session can resume. If STATUS.md exists, read it and resume at the recorded stage.

```
# <TICKER> initiation status
stage: 2-brief-review        # 1-facts | 2-brief-review | 3-model | 4-writing | 5-build | 6-review | done
updated: <date>
decisions: <Ethan's answers, e.g. holdings disclosure, thesis pillars, peers, assumption calls>
open: <what is waiting on whom>
```

## Stage 1: Facts (no questions needed)
1. `uv run erb facts TICKER`. Read `facts/facts.md` end to end, then note every NOTE line (ADR, no quarterlies, sections not found).
2. Read the filing excerpts in `facts/filings/`: 10-K Business and Risk Factors, both MD&As, and the latest earnings release. Skim for segment KPIs, guidance, one-offs and management's framing.
3. `uv run erb model TICKER --init` (a draft for reference only; it gives multiples vs history, calibrated margins and the model's warnings).

## Stage 2: Research brief, then STOP
1. Web research (WebSearch / WebFetch), primary sources first:
   - investor relations: latest earnings call transcript or prepared remarks, investor day, guidance
   - industry data: size, growth, share (industry bodies, government statistics, research firms; name the source and year)
   - an event timeline for the last 12–24 months (earnings reactions, guidance changes, M&A, regulation, competitors)
   - the Street debate: bull and bear arguments from reputable press; never invent analyst quotes or targets
2. Log every source in `sources.md` as you go (format in `guides/brief_template.md`). Only cite pages you actually opened.
3. Write `brief.md` following `guides/brief_template.md`. Every figure tagged `[Sn]` or `[F]`. Mark anything uncertain `[VERIFY: ...]`.
4. Update STATUS.md to `2-brief-review`, then **stop**. Give Ethan a short summary: the snapshot, 2–4 candidate thesis pillars, the proposed peers, the draft model's rating and warnings, and the "Questions for Ethan" list (always including the holdings disclosure). Wait for his answers.

## Stage 3: Model
1. Record Ethan's decisions in STATUS.md.
2. Edit `assumptions.yaml`: set `peers`; update CapEx/margin/growth from guidance and the thesis; replace each changed comment with `# why: ... [Sn]`. Keep the draft's consensus calibration unless the thesis argues otherwise. For adjusted EPS fill `eps_actual_overrides` from the earnings releases. ADRs: confirm the ratio.
3. `uv run erb model TICKER`. Resolve each WARNING (change the assumption with a reason, or note why it stands for the Valuation section). Iterate until the model tells the story the thesis argues, with every change defended. Never tune numbers to hit a desired rating.
4. Summarize for Ethan: rating, bear/base/bull PTs, the key assumption calls vs consensus. Proceed to writing unless he objects (the brief was the mandatory stop).

## Stage 4: Writing
1. `uv run erb scaffold TICKER` (never `--sample`), then fill `sections/*.md` in order 02 → 10, then 01, then 00 last (the cover summarizes everything).
2. Before writing, read `guides/style_guide.md` and the section's guide in `guides/section_guides/`. Voice: "our team", "the Fund", dense numbers, punny H2 subheadings, the rating and PTs only as `model.json` states them.
3. Tag every sentence that carries a figure: `[Sn]` for sourced facts, `[M]` for model outputs. Numbers you cannot source become `[VERIFY: ...]`.
4. Fill the cover front matter (tagline, CEO, HQ, employees, GICS, holdings disclosure from Ethan).

## Stage 5: Build and check
1. `uv run erb lint TICKER`. Fix every error; fix warnings unless a warning is a deliberate choice. Repeat until 0 errors.
2. `uv run erb build TICKER --word`. If Word is unavailable, `uv run erb build TICKER` (the .docx updates its TOC on open).
3. Render the PDF pages and look at every page: `uv run python -c "import pypdfium2 as p; d=p.PdfDocument('<pdf>'); [d[i].render(scale=1.4).to_pil().save(f'<scratch>/p{i+1:02d}.png') for i in range(len(d))]"`. Check for overflowing tables, orphaned headings, empty exhibits and anything that reads wrong. Fix the sections and rebuild.

## Stage 6: Hand-off
Tell Ethan: the file paths (.docx and .pdf), the rating and PTs, the open `[VERIFY]` items (list them), any model warnings left standing and why, and what you would strengthen with more time. Set STATUS.md to `6-review`. After his edits, loop through stages 4–5 again. Set `done` when he signs off.
