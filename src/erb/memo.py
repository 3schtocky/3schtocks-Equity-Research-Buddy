"""`erb memo TICKER`: one-page pitch memo skeleton for a screened name.

Auto-filled (numbers from the facts pack, the screen and the draft model); the narrative
sections are left as `[VERIFY: write ...]` prompts for the analyst (Claude) to fill after a
short research pass. Output: coverage/_screens/<date>/memos/<TICKER>.md
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from . import facts, fmt, valuation
from .config import COVERAGE_DIR, coverage_dir


def latest_screen() -> Path | None:
    d = COVERAGE_DIR / "_screens"
    runs = sorted(p for p in d.glob("*") if (p / "screen.csv").exists()) if d.exists() else []
    return runs[-1] if runs else None


def build(ticker: str, log=print, run_dir: Path | None = None, model: bool = True) -> Path:
    """`model=False` leaves the valuation out (for offices where only an approved model's numbers
    may be quoted); `run_dir` picks the screen run (default: the latest)."""
    t = ticker.upper()
    cdir = coverage_dir(t)
    log(f"Facts for {t}")
    facts.build(t, with_filings=False, log=lambda *_: None)
    m = None
    if model:
        if not (cdir / "assumptions.yaml").exists():  # never overwrite an initiation's assumptions
            (cdir / "assumptions.yaml").write_text(valuation.draft_assumptions(t))
        m = valuation.run(t, log=lambda *_: None)
    f = valuation.load_facts(t)
    c, mk = f["company"], f["company"]["market"]
    cur = c["financial_currency"]

    if m is not None:
        sc = m["scenarios"]
        valuation_lines = [
            f"- Draft model (consensus-calibrated, untuned): **{m['rating']['rating']}**, base PT {fmt.price(sc['base']['price_target'])} "
            f"({fmt.pct(sc['base']['price_return'])}), bear {fmt.price(sc['bear']['price_target'])}, bull {fmt.price(sc['bull']['price_target'])}",
            *[f"  - Model warning: {w}" for w in m["warnings"]]]
    else:
        valuation_lines = ["- Valuation: not modelled here; to be modelled by the Quant Department if researched."]

    run_dir = run_dir or latest_screen()
    rank_line = "Not in the latest screen."
    if run_dir is not None:
        s = pd.read_csv(run_dir / "screen.csv")
        ranked = s[s["factors_used"] >= 3].reset_index(drop=True)
        hit = ranked.index[ranked["ticker"] == t]
        if len(hit):
            r = ranked.loc[hit[0]]
            if "acceleration" in s.columns:   # a Gems run
                rank_line = (f"Gems screen {run_dir.name}: #{hit[0] + 1} of {len(ranked)} · composite {r['composite']:.2f} "
                             f"(acceleration {_s(r['acceleration'])}, growth {_s(r['growth'])}, margin {_s(r['margin'])}, "
                             f"momentum {_s(r['momentum'])}) · latest-quarter revenue YoY {fmt.pct(r['yoy_q'])} vs "
                             f"{fmt.pct(r['yoy_q1'])} the quarter before · sector group: {r['sector']}")
            else:
                rank_line = (f"Screen {run_dir.name}: #{hit[0] + 1} of {len(ranked)} · composite {r['composite']:.2f} "
                             f"(value {_s(r['value'])}, quality {_s(r['quality'])}, growth {_s(r['growth'])}, "
                             f"momentum {_s(r['momentum'])}) · sector group: {r['sector']}")

    a = f["annual"].dropna(subset=["revenue"]).tail(3)
    rows = [("Revenue", "revenue", lambda v: fmt.money(v, cur)), ("  YoY", "revenue_yoy", fmt.pct),
            ("Operating margin", "operating_margin", fmt.pct), ("FCF margin", "fcf_margin", fmt.pct),
            ("Diluted EPS", "eps_diluted", lambda v: fmt.price(v, cur)), ("Net debt", "net_debt", lambda v: fmt.money(v, cur)),
            ("ROIC", "roic", fmt.pct)]
    table = ["| | " + " | ".join(fmt.fy(int(y)) for y in a["fy"]) + " |", "|---|" + "---|" * len(a)]
    table += [f"| {label} | " + " | ".join(fn(v) for v in a[col]) + " |" for label, col, fn in rows]

    bands = c.get("multiple_bands") or {}
    pe = bands.get("ltm_pe") or {}
    ev = bands.get("ltm_ev_ebitda") or {}
    L = [f"# Pitch Memo: {mk.get('name') or c['name']} ({t})",
         f"{date.today()} · {fmt.price(mk['price'], mk.get('currency') or 'USD')} · market cap {fmt.money(mk.get('market_cap'))} · "
         f"{mk.get('sector')} / {mk.get('industry')}",
         f"{rank_line}", "",
         "## Why it screened", "[VERIFY: write 2-3 sentences on which factors drove the rank and whether they are durable or one-offs]", "",
         "## The pitch", "[VERIFY: write the 2-3 sentence thesis a full initiation would test]", "",
         "## Snapshot [F]", *table, "",
         "## Valuation and the Street [F][M]",
         f"- NTM P/E {fmt.multiple(mk.get('ntm_pe'))}; LTM P/E {fmt.multiple(pe.get('current'))} vs 1Y/3Y medians "
         f"{fmt.multiple(pe.get('median_1y'))} / {fmt.multiple(pe.get('median_3y'))}; LTM EV/EBITDA {fmt.multiple(ev.get('current'))} "
         f"vs 3Y median {fmt.multiple(ev.get('median_3y'))}",
         f"- Stock: YTD {fmt.pct(mk.get('ytd_return'))}, 1-year {fmt.pct(mk.get('one_year_return'))}, "
         f"52-week range {fmt.price(mk['week52_low'])}–{fmt.price(mk['week52_high'])}",
         f"- Street: mean PT {fmt.price(mk.get('target_mean'))} ({fmt.pct((mk.get('target_mean') or 0) / mk['price'] - 1 if mk.get('target_mean') else None)} upside), "
         f"{mk.get('n_analysts')} analysts",
         *valuation_lines, "",
         "## What could go wrong", "[VERIFY: write the 2-3 biggest risks]", "",
         "## Questions an initiation would answer", "[VERIFY: list 2-3 open questions]", "",
         "## Sources", *[f"- [F{i}] {n}: {u}" for i, (n, u) in enumerate(c["sources"], 1)]]
    run_dir = run_dir or (COVERAGE_DIR / "_screens" / str(date.today()))
    out = run_dir / "memos" / f"{t}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    log(f"Wrote {out}")
    return out


def _s(x) -> str:
    return "" if x is None or pd.isna(x) else f"{x:.2f}"
