"""`erb facts TICKER`: assemble the facts pack for an initiation.

Writes coverage/<TICKER>/facts/:
  facts.md                  human-readable summary with source list (start of brief.md)
  company.json              EDGAR profile + market snapshot
  financials_annual.csv     standardized annual statements + derived metrics
  financials_quarterly.csv  same, quarterly (derived quarters flagged in provenance)
  provenance.csv            item/period -> XBRL tag, accession, filing URL, derived flag
  segments.csv              segment / product / geography facts from the latest 10-K and 10-Q
  estimates.json            consensus (EPS, revenue, trend, revisions, targets, surprises)
  prices.csv                daily prices (5 years)
  multiples_history.csv     weekly LTM P/E and EV/EBITDA (point-in-time)
  filings/*.txt             Business, Risk Factors, MD&A, earnings release text
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from . import edgar, filings, financials, fmt, instance, market, segments
from .config import coverage_dir

ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def _profile(cik: int) -> dict:
    sub = edgar.submissions(cik)
    biz = sub.get("addresses", {}).get("business", {}) or {}
    fye = sub.get("fiscalYearEnd")
    return {
        "cik": cik,
        "edgar_name": sub.get("name"),
        "tickers": sub.get("tickers"),
        "exchanges": sub.get("exchanges"),
        "sic": sub.get("sic"),
        "sic_description": sub.get("sicDescription"),
        "fiscal_year_end_mmdd": fye,
        "state_of_incorporation": sub.get("stateOfIncorporation"),
        "business_address": ", ".join(x for x in (biz.get("city"), biz.get("stateOrCountry")) if x),
        "former_names": [f.get("name") for f in sub.get("formerNames", [])],
        "filer_category": sub.get("category"),
        "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
    }


def build(ticker: str, with_filings: bool = True, refresh: bool = False, log=print) -> dict:
    company = edgar.lookup(ticker)
    out_dir = coverage_dir(company.ticker) / "facts"
    out_dir.mkdir(parents=True, exist_ok=True)
    sources: list[tuple[str, str]] = []
    notes: list[str] = []

    log(f"EDGAR profile and XBRL facts for {company.name} (CIK {company.cik})")
    profile = _profile(company.cik)
    cf = edgar.company_facts(company.cik, refresh=refresh)
    annual_filing = edgar.latest(company.cik, ANNUAL_FORMS)
    quarter_filing = edgar.latest(company.cik, ("10-Q",))
    er_filing = edgar.latest(company.cik, ("8-K",), items_contains="2.02")
    for f in (annual_filing, quarter_filing):
        if f is not None:  # companyfacts can lag new filings; read the latest instances directly
            try:
                instance.merge(cf, instance.facts(f))
            except Exception as exc:
                notes.append(f"Could not read XBRL instance for {f.form} {f.accession}: {exc}")
    fin = financials.build(cf)
    annual, quarterly, currency = fin["annual"], fin["quarterly"], fin["currency"]
    prov = financials.provenance_frame(fin["provenance"], company.cik)
    annual.to_csv(out_dir / "financials_annual.csv")
    quarterly.to_csv(out_dir / "financials_quarterly.csv")
    prov.to_csv(out_dir / "provenance.csv", index=False)
    sources.append(("SEC EDGAR XBRL company facts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik:010d}.json"))

    log("Segments from XBRL instances")
    seg_frames = []
    for f in (annual_filing, quarter_filing):
        if f is None:
            continue
        try:
            seg_frames.append(segments.extract(f))
        except Exception as exc:
            notes.append(f"Segment extraction failed for {f.form} {f.accession}: {exc}")
    seg = pd.concat(seg_frames, ignore_index=True) if seg_frames else pd.DataFrame()
    seg.to_csv(out_dir / "segments.csv", index=False)

    if with_filings:
        log("Filing text (Business, Risk Factors, MD&A, earnings release)")
        fdir = out_dir / "filings"
        fdir.mkdir(exist_ok=True)
        for old in fdir.glob("*.txt"):  # don't leave stale excerpts from earlier runs
            old.unlink()
        for f in (annual_filing, quarter_filing):
            if f is None:
                continue
            secs = filings.sections(f)
            for name, text in secs.items():
                if name == "full_text":
                    continue
                path = fdir / f"{f.form.replace('/', '')}_{f.report_date}_{name}.txt"
                path.write_text(f"Source: {f.form} for period ending {f.report_date}, filed {f.filing_date}\n{f.url}\n\n{text}")
            missing = {n for n, *_ in filings.SECTIONS.get(f.form, [])
                       if (f.form, n) not in filings.OPTIONAL} - set(secs)
            if missing:
                notes.append(f"{f.form} sections not found automatically: {', '.join(sorted(missing))} "
                             f"(full text saved as {f.form}_{f.report_date}_full_text.txt)")
                (fdir / f"{f.form.replace('/', '')}_{f.report_date}_full_text.txt").write_text(f"Source: {f.url}\n\n{secs['full_text']}")
            sources.append((f"{f.form} for period ending {f.report_date} (filed {f.filing_date})", f.url))
        if er_filing is not None:
            er = filings.earnings_release(er_filing)
            if er:
                text, url = er
                (fdir / f"8-K_{er_filing.filing_date}_earnings_release.txt").write_text(f"Source: {url}\n\n{text}")
                sources.append((f"8-K earnings release (filed {er_filing.filing_date})", url))

    log("Market data and consensus (Yahoo Finance)")
    prices = market.history(company.ticker, "5y")
    prices.to_csv(out_dir / "prices.csv")
    snap = market.snapshot(company.ticker, prices)
    est = market.estimates(company.ticker)
    (out_dir / "estimates.json").write_text(json.dumps(est, indent=2, default=str))
    sources.append(("Yahoo Finance quote and statistics", snap["source"]))
    sources.append(("Yahoo Finance analyst estimates", est["source"]))

    # Yahoo's nextFiscalYearEnd is the end of the current (in-progress) fiscal year
    snap["ntm_eps"] = market.ntm(est, snap["next_fiscal_year_end"], snap["as_of"])
    snap["ntm_pe"] = snap["price"] / snap["ntm_eps"] if snap.get("ntm_eps") and snap["ntm_eps"] > 0 else None

    bands = {}
    has_quarters = bool(quarterly["revenue"].notna().any())
    if not has_quarters:
        notes.append("No quarterly XBRL financials (foreign private issuers file annual 20-F only). "
                     "Use 6-K earnings releases from the company's IR site for recent quarters.")
    cross_currency = bool(snap.get("currency")) and snap["currency"] != currency
    if has_quarters and not cross_currency:
        filed = {row.period: row.first_filed for row in prov[prov["item"] == "eps_diluted"].itertuples()}
        mh = market.multiples_history(prices, quarterly, filed)
        mh.to_csv(out_dir / "multiples_history.csv")
        bands = {"ltm_pe": market.median_bands(mh, "ltm_pe"), "ltm_ev_ebitda": market.median_bands(mh, "ltm_ev_ebitda")}
    elif cross_currency:
        notes.append(f"Financials are in {currency} but the listing trades in {snap.get('currency')} "
                     "(likely an ADR). Multiples history skipped; Yahoo's EV and EV/EBITDA are unreliable here (mixed currencies). "
                     "Check the ADR ratio before comparing per-share figures.")

    company_json = {"ticker": company.ticker, "name": company.name, "edgar": profile, "market": snap,
                    "financial_currency": currency, "multiple_bands": bands,
                    "filings": {k: (vars(v) if v else None) for k, v in
                                {"annual": annual_filing, "quarterly": quarter_filing, "earnings_8k": er_filing}.items()},
                    "notes": notes, "sources": sources, "generated": date.today().isoformat()}
    edgar.save_json(company_json, out_dir / "company.json")
    (out_dir / "facts.md").write_text(render_md(company_json, annual, quarterly, seg, est))
    log(f"Wrote {out_dir}")
    for n in notes:
        log(f"NOTE: {n}")
    return company_json


def _row(label, values):
    return f"| {label} | " + " | ".join(values) + " |"


def render_md(c: dict, annual: pd.DataFrame, quarterly: pd.DataFrame, seg: pd.DataFrame, est: dict) -> str:
    m, e, cur = c["market"], c["edgar"], c["financial_currency"]
    L = [f"# {c['name']} ({c['ticker']}): Facts Pack",
         f"Generated {c['generated']}. Prices as of the {m['as_of']} close. Figures from SEC filings unless noted.",
         "", "## Company"]
    L += [f"- **Legal name:** {m.get('name') or e['edgar_name']} · CIK {e['cik']} · {', '.join(e['exchanges'] or [])}",
          f"- **HQ:** {m.get('hq') or e['business_address']} · **Employees:** {fmt.number(m.get('employees'), 1)} (Yahoo)",
          f"- **Sector / industry (Yahoo):** {m.get('sector')} / {m.get('industry')} · **SIC:** {e['sic']} {e['sic_description']}",
          f"- **Fiscal year end:** {e['fiscal_year_end_mmdd']} · **Next earnings:** {m.get('next_earnings_date')}",
          f"- **Former names:** {', '.join(e['former_names']) or 'none'}",
          "", f"> {m.get('summary') or ''}  \n> (Yahoo Finance business summary; verify against 10-K Item 1)", ""]

    L += ["## Market Snapshot",
          "| Metric | Value |", "|---|---|",
          f"| Price | {fmt.price(m['price'], m.get('currency') or 'USD')} |",
          f"| 52-week range | {fmt.price(m['week52_low'])} – {fmt.price(m['week52_high'])} |",
          f"| YTD / 1-year return | {fmt.pct(m['ytd_return'])} / {fmt.pct(m['one_year_return'])} |",
          f"| Market cap / EV | {fmt.money(m['market_cap'])} / {fmt.money(m['enterprise_value'])} |",
          f"| Dividend yield | {fmt.pct(m['dividend_yield'])} |",
          f"| Beta | {m['beta']} |",
          f"| NTM EPS (consensus blend) / NTM P/E | {fmt.price(m.get('ntm_eps'))} / {fmt.multiple(m.get('ntm_pe'))} |",
          f"| Trailing P/E / Fwd P/E / EV/EBITDA (Yahoo) | {fmt.multiple(m['trailing_pe'])} / {fmt.multiple(m['forward_pe'])} / {fmt.multiple(m['ev_ebitda'])} |",
          f"| Street PT mean / median (n={m.get('n_analysts')}) | {fmt.price(m.get('target_mean'))} / {fmt.price(m.get('target_median'))} |", ""]
    for key, name in (("ltm_pe", "LTM P/E"), ("ltm_ev_ebitda", "LTM EV/EBITDA")):
        b = c["multiple_bands"].get(key)
        if b:
            L.append(f"- **{name}:** current {fmt.multiple(b['current'])} vs medians 1Y {fmt.multiple(b['median_1y'])}, "
                     f"2Y {fmt.multiple(b['median_2y'])}, 3Y {fmt.multiple(b['median_3y'])} (point-in-time, from filings + prices)")
    L.append("")

    a = annual.tail(5)
    L += ["## Annual Financials (" + cur + ")", _row("", [fmt.fy(int(y)) for y in a["fy"]]),
          "|---|" + "---|" * len(a)]
    for label, col, kind in [("Revenue", "revenue", "m"), ("  YoY", "revenue_yoy", "p"), ("Gross margin", "gross_margin", "p"),
                             ("Operating income", "operating_income", "m"), ("  Operating margin", "operating_margin", "p"),
                             ("EBITDA margin", "ebitda_margin", "p"), ("Net income", "net_income", "m"),
                             ("Diluted EPS", "eps_diluted", "e"), ("  YoY", "eps_diluted_yoy", "p"),
                             ("R&D % rev", "rnd_pct", "p"), ("SG&A % rev", "sga_pct", "p"),
                             ("CFO", "cfo", "m"), ("CapEx", "capex", "m"), ("FCF", "fcf", "m"),
                             ("Net debt", "net_debt", "m"), ("ROE", "roe", "p"), ("ROIC", "roic", "p")]:
        f = {"m": lambda x: fmt.money(x, cur), "p": fmt.pct, "e": lambda x: fmt.price(x, cur)}[kind]
        L.append(_row(label, [f(v) for v in a[col]]))
    L.append("")

    q = quarterly.dropna(subset=["revenue"]).tail(8)
    if not q.empty:
        L += ["## Recent Quarters (" + cur + ")", _row("", [fmt.quarter(int(r.fy), int(r.q)) for r in q.itertuples()]),
              "|---|" + "---|" * len(q)]
        for label, col, kind in [("Revenue", "revenue", "m"), ("  YoY", "revenue_yoy", "p"),
                                 ("Operating margin", "operating_margin", "p"), ("Diluted EPS", "eps_diluted", "e"),
                                 ("FCF", "fcf", "m")]:
            f = {"m": lambda x: fmt.money(x, cur), "p": fmt.pct, "e": lambda x: fmt.price(x, cur)}[kind]
            L.append(_row(label, [f(v) for v in q[col]]))
        L += ["", "_Q4 and some quarters are derived (FY minus 9M, or YTD differences). See provenance.csv._", ""]

    total = annual["revenue"].dropna().iloc[-1] if annual["revenue"].notna().any() else None
    for dim in ("segment", "product", "geography"):
        mix = segments.latest_mix(seg, dim, total)
        if mix is None or mix.empty:
            continue
        L += [f"## Revenue by {dim.title()} ({mix['end'].iloc[0]})", "| Member | Revenue | % of total |", "|---|---|---|"]
        L += [f"| {r.label} | {fmt.money(r.value, cur)} | {fmt.pct(r.pct)} |" for r in mix.itertuples()]
        if mix["overlap"].iloc[0]:
            L.append("\n_Members overlap (nested regions or sub-lines); percentages are of consolidated revenue._")
        L.append("")

    L += ["## Consensus (Yahoo Finance)", "| Period | EPS avg | EPS low–high | # | Revenue avg | Rev growth |", "|---|---|---|---|---|---|"]
    rev = {r.get("period"): r for r in est.get("revenue_estimate", [])}
    for r in est.get("earnings_estimate", []):
        rv = rev.get(r.get("period"), {})
        ec, rc = r.get("currency") or "USD", rv.get("currency") or "USD"
        L.append(f"| {r.get('period')} | {fmt.price(r.get('avg'), ec)} | {fmt.price(r.get('low'), ec)}–{fmt.price(r.get('high'), ec)} | "
                 f"{r.get('numberOfAnalysts')} | {fmt.money(rv.get('avg'), rc)} | {fmt.pct(rv.get('growth'))} |")
    hist = [h for h in est.get("earnings_history", []) if h.get("Reported EPS") is not None][:4]
    if hist:
        def surprise(h: dict) -> str:   # thinly covered names report EPS with no estimate
            s = h.get("Surprise(%)")
            return f"({s:+.1f}%)" if isinstance(s, (int, float)) and s == s else "(no surprise data)"

        L += ["", "Recent EPS surprises: " + "; ".join(
            f"{h['Earnings Date']}: {fmt.price(h['Reported EPS'])} vs {fmt.price(h.get('EPS Estimate'))} est "
            f"{surprise(h)}" for h in hist)]
    L.append("")

    if c["notes"]:
        L += ["## Notes"] + [f"- {n}" for n in c["notes"]] + [""]
    L += ["## Sources"] + [f"- [F{i}] {name}: {url}" for i, (name, url) in enumerate(c["sources"], 1)]
    return "\n".join(L) + "\n"
