"""`erb scaffold TICKER`: write sections/*.md skeletons with exhibit tokens and guidance.

Guidance lives in HTML comments (dropped at build). `--sample` fills paragraphs with
clearly-marked layout filler so page flow can be checked before real writing.
"""

from __future__ import annotations

from datetime import date

from .config import coverage_dir

FILLER = ("[SAMPLE LAYOUT TEXT] This paragraph stands in for analyst prose while the layout is checked. "
          "A finished paragraph runs five to eight dense sentences, each carrying a sourced figure, a date "
          "or a named entity, and closes with what it means for the stock. ") * 2

SECTIONS = {
    "00_cover.md": """---
tagline: "{tagline}"          # one exclamatory pun on the name or business
report_date: {today}
holdings_disclosure: "The author does not hold a position in {ticker}."   # update per report
ceo: ""                       # [Sn] from proxy / IR site
hq: ""
employees: ""                 # from 10-K Item 1 (human capital)
gics_sector: ""
gics_sub_industry: ""
---
<!-- guides/section_guides/00_cover.md. 4-5 bullets, each 3-5 lines with hard numbers.
     Last bullet: rating + base PT + implied return, all from model.json. -->
{bullets}

## Company Overview

<!-- 4-6 sentences: what it does, scale, history, segments, next earnings date. -->
{para}
""",
    "01_investment_summary.md": """# Investment Summary
<!-- guides/section_guides/01_investment_summary.md. "## Bull/Base/Bear Case" headings are replaced
     with the price target and return from model.json. Write the narrative only. -->

## Bull Case
{para}

## Base Case
{para}

## Bear Case
{para}

{{{{price_targets}}}}

{{{{company_snapshot}}}}
""",
    "02_industry_overview.md": """# Industry Overview
<!-- guides/section_guides/02_industry_overview.md. 4-7 punny subsections, recent sourced industry data. -->

## [Pun Heading One]
{para}

## [Pun Heading Two]
{para}

## [Pun Heading Three]
{para}
""",
    "03_business_overview.md": """# Business Overview
<!-- guides/section_guides/03_business_overview.md. One subsection per segment: "Name (xx.x% of FY'25 Revenue)". -->
{para}

{{{{segment_mix}}}}

## [Segment A (xx.x% of FY'25 Revenue)]
{para}

## [Segment B (xx.x% of FY'25 Revenue)]
{para}
""",
    "04_undervaluation_thesis.md": """# Undervaluation & Thesis
<!-- guides/section_guides/04_undervaluation_thesis.md. Open with NTM P/E vs its medians (facts.md). -->
{para}

## [Pun Heading: what happened to the multiple]
{para}

## [Pun Heading: why the Street is wrong]
{para}

{{{{band_pe}}}}

{{{{band_ev_ebitda}}}}
""",
    "05_catalysts_drivers.md": """# Catalysts & Drivers
<!-- guides/section_guides/05_catalysts_drivers.md. Mechanism + quantified impact + timing for each. -->
{para}

## [Catalyst One]
{para}

## [Catalyst Two]
{para}

## [Catalyst Three]
{para}
""",
    "06_risks.md": """# Risks to Investment Thesis
<!-- guides/section_guides/06_risks.md. Each risk: downside paragraph, then a "- **Mitigant:**" bullet. -->

## [Risk One]
{para}

- **Mitigant:** {short}

## [Risk Two]
{para}

- **Mitigant:** {short}
""",
    "07_peer_group.md": """# Peer Group Analysis
<!-- guides/section_guides/07_peer_group.md. One short profile per peer, then the comps tables. -->

**[Peer One, Inc. (PEER1)]** {short}

**[Peer Two, Inc. (PEER2)]** {short}

{{{{comps}}}}
""",
    "08_valuation.md": """# Valuation Analysis
<!-- guides/section_guides/08_valuation.md. Explain the judgment behind assumptions; numbers come from model.json. -->

## Model Assumptions
{para}

{{{{assumptions}}}}

{{{{dcf}}}}

{{{{sensitivity}}}}

{{{{football_field}}}}
""",
    "09_financial_analysis.md": """# Financial Analysis
<!-- guides/section_guides/09_financial_analysis.md. Mostly exhibits; one short paragraph on inflections. -->

{{{{financial_summary}}}}

{{{{financial_grid}}}}

{short}
""",
    "10_appendix.md": """# Appendix
<!-- guides/section_guides/10_appendix.md -->

## Exhibit I: Bulls vs Bears
**Bulls:**

- {short}
- {short}

**Bears:**

- {short}
- {short}

## Exhibit II: Exit Strategy
{para}
""",
}


def scaffold(ticker: str, sample: bool = False, force: bool = False, log=print) -> None:
    sdir = coverage_dir(ticker) / "sections"
    sdir.mkdir(parents=True, exist_ok=True)
    para = FILLER.strip() if sample else "[VERIFY: write this paragraph]"
    short = FILLER[:240].strip() if sample else "[VERIFY: write this]"
    bullets = "\n".join(f"- {FILLER[:330].strip()}" if sample else "- [VERIFY: thesis bullet]" for _ in range(5))
    for name, tpl in SECTIONS.items():
        path = sdir / name
        if path.exists() and not force:
            log(f"skip {path.name} (exists)")
            continue
        path.write_text(tpl.format(para=para, short=short, bullets=bullets, ticker=ticker.upper(),
                                   today=date.today().isoformat(),
                                   tagline="[SAMPLE] Placeholder Tagline!" if sample else "[VERIFY: tagline]"))
        log(f"wrote {path.relative_to(sdir.parent.parent)}")
