"""`erb screen`: rank all US-listed equities (NYSE, Nasdaq, NYSE American/CBOE; ADRs included) on
value, quality, growth and momentum.

Data
- Universe: SEC company_tickers_exchange.json (OTC excluded).
- Fundamentals: SEC XBRL frames (one request returns a concept for every US-GAAP filer).
  IFRS filers (most ADRs) are not in the frames API; their ratios come from SEC company facts.
- Prices: Yahoo Finance bulk download (13 months, adjusted) for market cap and momentum.
- Sector: SIC code from SEC submissions (cached 30 days), mapped to broad groups.

Factors (percentile ranks, higher is better)
- value    (within sector group): earnings yield, FCF yield, EBIT / EV
- quality  (within sector group): ROIC, operating margin, FCF margin
- growth   (whole universe): CY'25 revenue growth, latest-quarter revenue growth YoY
- momentum (whole universe): 12-month return excluding the last month
Composite = weighted mean of factor scores (default 30/30/20/20); a missing factor counts as 0.5 (neutral). Financials and REITs
get value from earnings yield and quality from ROE, because EBIT, EV and FCF do not describe them.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from . import edgar, fmt, market
from .config import CACHE_DIR, COVERAGE_DIR

EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}
DEFAULT_WEIGHTS = {"value": 0.30, "quality": 0.30, "growth": 0.20, "momentum": 0.20}

REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense", "SalesRevenueNet"]


def _periods(today: date) -> dict:
    """Latest calendar year whose annual reports are out (~April) and the latest quarter that
    ended at least 45 days ago (so its 10-Qs are filed)."""
    from datetime import timedelta
    y = today.year - 1 if today.month >= 4 else today.year - 2
    cutoff = today - timedelta(days=45)
    qy, q = cutoff.year, (cutoff.month - 1) // 3  # quarter fully ended before the cutoff month's quarter
    if q == 0:
        qy, q = qy - 1, 4
    return {"cy": f"CY{y}", "cy_prev": f"CY{y - 1}", "q": f"CY{qy}Q{q}", "q_prev": f"CY{qy - 1}Q{q}",
            "inst": [f"CY{qy}Q{q}I", f"CY{y}Q4I"]}


def _frame(tag: str, period: str, unit: str = "USD", taxonomy: str = "us-gaap") -> pd.Series:
    try:
        d = edgar.frames(tag, unit, period, taxonomy=taxonomy)
    except Exception:
        return pd.Series(dtype=float)
    return pd.Series({r["cik"]: r["val"] for r in d["data"]}, dtype=float)


def _first(tags: list[str], period: str, how: str = "first", unit: str = "USD") -> pd.Series:
    series = [_frame(t, period, unit) for t in tags]
    series = [s for s in series if not s.empty]
    if not series:
        return pd.Series(dtype=float)
    df = pd.concat(series, axis=1)
    return df.max(axis=1) if how == "max" else df.bfill(axis=1).iloc[:, 0]


def _instant(tags: list[str], periods: list[str]) -> pd.Series:
    out = pd.Series(dtype=float)
    for p in periods:  # latest instant first; older fills gaps
        s = _first(tags, p)
        out = out.combine_first(s) if not out.empty else s
    return out


def fundamentals(periods: dict, log=print) -> pd.DataFrame:
    log(f"SEC frames: {periods['cy']}, {periods['cy_prev']}, {periods['q']} vs {periods['q_prev']}")
    f = pd.DataFrame({
        "revenue": _first(REV_TAGS, periods["cy"], "max"),
        "revenue_prev": _first(REV_TAGS, periods["cy_prev"], "max"),
        "revenue_q": _first(REV_TAGS, periods["q"], "max"),
        "revenue_q_prev": _first(REV_TAGS, periods["q_prev"], "max"),
        "operating_income": _first(["OperatingIncomeLoss"], periods["cy"]),
        "net_income": _first(["NetIncomeLoss", "ProfitLoss"], periods["cy"]),
        "cfo": _first(["NetCashProvidedByUsedInOperatingActivities"], periods["cy"]),
        "capex": _first(["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"], periods["cy"]),
        "shares": _first(["WeightedAverageNumberOfDilutedSharesOutstanding"], periods["q"], unit="shares")
        .combine_first(_first(["WeightedAverageNumberOfDilutedSharesOutstanding"], periods["cy"], unit="shares")),
        "equity": _instant(["StockholdersEquity"], periods["inst"]),
        "debt": _instant(["LongTermDebt", "LongTermDebtNoncurrent", "DebtLongtermAndShorttermCombinedAmount"], periods["inst"]),
        "cash": _instant(["CashAndCashEquivalentsAtCarryingValue",
                          "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], periods["inst"]),
    })
    f.index.name = "cik"
    return f


SIC_CACHE = CACHE_DIR / "sic_map.json"


def sic_codes(ciks: list[int], log=print) -> dict[int, tuple]:
    cache = json.loads(SIC_CACHE.read_text()) if SIC_CACHE.exists() else {}
    if SIC_CACHE.exists() and time.time() - SIC_CACHE.stat().st_mtime > 30 * 86400:
        cache = {}
    missing = [c for c in ciks if str(c) not in cache]
    if missing:
        log(f"SIC codes for {len(missing)} companies (cached 30 days)")
    for i, c in enumerate(missing, 1):
        try:
            sub = edgar.submissions(c)
            forms = set(sub["filings"]["recent"]["form"][:40])
            cache[str(c)] = [int(sub.get("sic") or 0), bool(forms & {"20-F", "40-F", "20-F/A", "40-F/A"})]
        except Exception:
            cache[str(c)] = [0, False]
        if i % 250 == 0:
            SIC_CACHE.write_text(json.dumps(cache))
            log(f"  {i}/{len(missing)}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SIC_CACHE.write_text(json.dumps(cache))
    out = {}
    for c in ciks:
        v = cache.get(str(c), [0, False])
        out[c] = tuple(v) if isinstance(v, list) else (int(v), False)
    return out


def sector_group(sic: int) -> str:
    if sic == 6798:
        return "REITs"
    if 6000 <= sic < 6800:
        return "Financials"
    if 1000 <= sic < 1500 or 2900 <= sic < 3000:
        return "Energy & Mining"
    if 4900 <= sic < 5000:
        return "Utilities"
    if 2830 <= sic < 2840 or 3840 <= sic < 3860 or 8000 <= sic < 8100:
        return "Health Care"
    if 3570 <= sic < 3580 or 3600 <= sic < 3700 or 7370 <= sic < 7380 or 4800 <= sic < 4900:
        return "Tech, Media & Telecom"
    if 5000 <= sic < 6000 or 7000 <= sic < 7100 or 2000 <= sic < 2400:
        return "Consumer & Retail"
    if 1500 <= sic < 1800 or 3000 <= sic < 4000 or 4000 <= sic < 4800 or 2400 <= sic < 2900:
        return "Industrials & Materials"
    if 7000 <= sic < 9000:
        return "Services"
    return "Other"


def prices(tickers: list[str], log=print) -> tuple[pd.DataFrame, pd.DataFrame]:
    """13 months of adjusted closes and volumes for all tickers (cached for the day)."""
    path = CACHE_DIR / f"screen_prices_{date.today()}.pkl"
    if path.exists():
        cached = pd.read_pickle(path)
        if isinstance(cached, tuple):
            return cached
    symbols = {market._yf_symbol(t): t for t in tickers}
    closes, vols = [], []
    chunks = [list(symbols)[i:i + 250] for i in range(0, len(symbols), 250)]
    for i, chunk in enumerate(chunks, 1):
        log(f"Yahoo prices {i}/{len(chunks)}")
        df = yf.download(chunk, period="13mo", auto_adjust=True, progress=False, threads=True)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            closes.append(df["Close"])
            vols.append(df["Volume"])
        else:
            closes.append(df[["Close"]].rename(columns={"Close": chunk[0]}))
            vols.append(df[["Volume"]].rename(columns={"Volume": chunk[0]}))
    px = pd.concat(closes, axis=1).rename(columns=symbols)
    vol = pd.concat(vols, axis=1).rename(columns=symbols)
    px, vol = px.loc[:, ~px.columns.duplicated()], vol.loc[:, ~vol.columns.duplicated()]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.to_pickle((px, vol), path)
    return px, vol


YAHOO_KEYS = ["longName", "marketCap", "enterpriseValue", "totalRevenue", "revenueGrowth", "operatingMargins",
              "profitMargins", "returnOnEquity", "freeCashflow", "ebitda", "forwardPE", "trailingPE", "sector",
              "industry", "currency", "financialCurrency", "targetMeanPrice", "recommendationKey",
              "numberOfAnalystOpinions", "quoteType"]


def _yahoo_info(ticker: str, retries: int = 4) -> dict:
    for attempt in range(retries):
        try:
            i = yf.Ticker(market._yf_symbol(ticker)).info or {}
            if i.get("quoteType") or i.get("marketCap"):
                return {k: i.get(k) for k in YAHOO_KEYS}
        except Exception as exc:
            if "Rate" not in type(exc).__name__ and "429" not in str(exc):
                return {}
        time.sleep(5 * 3 ** attempt)  # 5s, 15s, 45s, 135s on rate limits
    return {}


def yahoo_info(tickers: list[str], log=print, pause: float = 1.0) -> pd.DataFrame:
    """Sequential and throttled (Yahoo rate-limits bursts); only successful lookups are cached."""
    path = CACHE_DIR / f"screen_yahoo_{date.today()}.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    cache = {k: v for k, v in cache.items() if v and any(x is not None for x in v.values())}
    todo = [t for t in tickers if t not in cache]
    if todo:
        log(f"Yahoo company data for {len(todo)} tickers (throttled)")
    for i, t in enumerate(todo, 1):
        info = _yahoo_info(t)
        if info:
            cache[t] = info
        if i % 20 == 0:
            path.write_text(json.dumps(cache))
            log(f"  {i}/{len(todo)}")
        time.sleep(pause)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache))
    return pd.DataFrame({t: cache.get(t, {}) for t in tickers}).T.reindex(columns=YAHOO_KEYS)


def _pct(s: pd.Series, groups: pd.Series | None = None) -> pd.Series:
    s = s.replace([np.inf, -np.inf], np.nan)
    if groups is None:
        return s.rank(pct=True)
    return s.groupby(groups).rank(pct=True)


def score(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    d = df.copy()
    fin = d["sector"].isin(["Financials", "REITs"])
    d["ev"] = d["market_cap"] + d["debt"].fillna(0) - d["cash"].fillna(0)
    d["earnings_yield"] = d["net_income"] / d["market_cap"]
    d["fcf"] = d["cfo"] - d["capex"].fillna(0)
    d["fcf_yield"] = (d["fcf"] / d["market_cap"]).where(~fin)
    d["ebit_ev"] = (d["operating_income"] / d["ev"]).where(~fin & (d["ev"] > 0))
    invested = (d["equity"] + d["debt"].fillna(0) - d["cash"].fillna(0)).where(lambda x: x > 0)
    d["roic"] = (d["operating_income"] * 0.79 / invested).where(~fin)
    d["roe"] = d["net_income"] / d["equity"].where(d["equity"] > 0)
    d["op_margin"] = (d["operating_income"] / d["revenue"]).where(~fin)
    d["fcf_margin"] = (d["fcf"] / d["revenue"]).where(~fin)
    d["rev_growth"] = d["revenue"] / d["revenue_prev"].where(d["revenue_prev"] > 0) - 1
    d["rev_growth_q"] = d["revenue_q"] / d["revenue_q_prev"].where(d["revenue_q_prev"] > 0) - 1
    # clip outliers so a few extreme values don't dominate percentile ties
    for c, lo, hi in (("roic", -1, 2), ("roe", -1, 2), ("rev_growth", -0.9, 3), ("rev_growth_q", -0.9, 3)):
        d[c] = d[c].clip(lo, hi)

    g = d["sector"]
    ratio_only = d["data_source"].eq("Yahoo (ratios)")
    for c in ("ebit_ev", "fcf_yield", "fcf_margin", "roic"):
        d.loc[ratio_only, c] = np.nan
    d["value"] = pd.concat([_pct(d["earnings_yield"], g), _pct(d["fcf_yield"], g), _pct(d["ebit_ev"], g)], axis=1).mean(axis=1)
    quality_parts = [_pct(d["roic"], g), _pct(d["op_margin"], g), _pct(d["fcf_margin"], g)]
    d["quality"] = pd.concat(quality_parts, axis=1).mean(axis=1)
    d.loc[fin, "quality"] = _pct(d["roe"], g)[fin]
    d["growth"] = pd.concat([_pct(d["rev_growth"]), _pct(d["rev_growth_q"])], axis=1).mean(axis=1)
    d["momentum"] = _pct(d["mom_12_1"])
    # a missing factor counts as neutral (0.5) so missing data neither helps nor hurts a name
    d["factors_used"] = pd.DataFrame({k: d[k].notna() for k in weights}).sum(axis=1)
    parts = pd.DataFrame({k: d[k].fillna(0.5) * w for k, w in weights.items()})
    d["composite"] = (parts.sum(axis=1) / sum(weights.values())).where(d["factors_used"] > 0)
    return d


def ifrs_ratios(cik: int) -> dict:
    """Currency-neutral fundamentals for foreign filers from SEC company facts (IFRS or US GAAP)."""
    from . import financials, instance
    try:
        cf = edgar.company_facts(cik)
        f = edgar.latest(cik, ("20-F", "40-F", "10-K"))
        if f is not None:
            instance.merge(cf, instance.facts(f))
        a = financials.build(cf)["annual"].dropna(subset=["revenue"])
    except Exception:
        return {}
    if len(a) < 2:
        return {}
    r, prev = a.iloc[-1], a.iloc[-2]
    return {"rev_growth": r["revenue"] / prev["revenue"] - 1 if prev["revenue"] > 0 else np.nan,
            "op_margin": r["operating_margin"], "fcf_margin": r["fcf_margin"], "roic": r.get("roic"),
            "roe": r.get("roe"), "fy": int(r["fy"])}


def run(min_cap: float = 2e9, top: int = 30, weights: dict | None = None, min_adv: float = 20e6, log=print) -> Path:
    weights = weights or DEFAULT_WEIGHTS
    today = date.today()
    periods = _periods(today)
    universe = pd.DataFrame([vars(c) for c in edgar.all_tickers()])
    universe = universe[universe["exchange"].isin(EXCHANGES)]
    universe = universe[~universe["ticker"].str.contains(r"-(?:W|WT|U|R|P[A-Z]?)$|\.(?:W|U|R)$", regex=True)]
    universe = universe.drop_duplicates("cik")  # one line per company (first listed class)
    log(f"Universe: {len(universe)} companies on {', '.join(sorted(EXCHANGES))}")

    df = universe.set_index("cik").join(fundamentals(periods, log), how="left")
    px, vol = prices(df["ticker"].tolist(), log)
    last = px.ffill().iloc[-1]
    df["price"] = df["ticker"].map(last)
    recent = px.index[-1] - pd.Timedelta(days=90)
    adv = (px[px.index >= recent] * vol[vol.index >= recent]).mean()
    df["adv"] = df["ticker"].map(adv)
    ago_12 = px.index[-1] - pd.Timedelta(days=365)
    ago_1 = px.index[-1] - pd.Timedelta(days=30)
    p12 = px[px.index <= ago_12].ffill().iloc[-1] if (px.index <= ago_12).any() else px.bfill().iloc[0]
    p1 = px[px.index <= ago_1].ffill().iloc[-1]
    df["mom_12_1"] = df["ticker"].map(p1 / p12 - 1)
    df["ret_1m"] = df["ticker"].map(last / p1 - 1)
    df["pct_off_high"] = df["ticker"].map(last / px.max() - 1)
    df["market_cap"] = df["price"] * df["shares"]
    df["data_source"] = np.where(df["revenue"].notna(), "SEC", "SEC (partial)")

    # Liquid names: market cap filter where we can compute it, dollar volume where we cannot
    has_cap = df["market_cap"].notna()
    keep = (df["price"] >= 5) & ((has_cap & (df["market_cap"] >= min_cap)) | (~has_cap & (df["adv"] >= min_adv)))
    df = df[keep]
    log(f"After filters (market cap >= {fmt.money(min_cap)} or, without SEC shares, "
        f"ADV >= {fmt.money(min_adv)}; price >= $5): {len(df)} companies")

    info = sic_codes(df.index.tolist(), log)
    df["sic"] = df.index.map(lambda c: info[c][0])
    df["foreign_filer"] = df.index.map(lambda c: info[c][1])
    df = df[df["sic"] != 6770]  # blank-check shells / SPACs
    df["sector"] = df["sic"].map(sector_group)

    foreign = df[df["foreign_filer"] & df["revenue"].isna()]
    if len(foreign):
        log(f"SEC company facts for {len(foreign)} foreign filers (20-F/40-F)")
    ratios = {}
    for cik in foreign.index:
        ratios[cik] = ifrs_ratios(cik)
    scored = score(df, weights)
    for cik, r in ratios.items():
        if not r:
            continue
        for k in ("rev_growth", "op_margin", "fcf_margin", "roic", "roe"):
            if r.get(k) is not None and not pd.isna(r.get(k)):
                scored.at[cik, k] = r[k]
        scored.at[cik, "data_source"] = f"SEC 20-F FY{r['fy']} (no value factor)"
    scored = rescore(scored, weights)
    ranked = scored[scored["factors_used"] >= 3].sort_values("composite", ascending=False)
    partial = scored[scored["factors_used"] < 3]
    log(f"Ranked {len(ranked)} companies with at least 3 of 4 factors; {len(partial)} held back for missing data")

    enrich = yahoo_info(ranked.head(max(top, 40))["ticker"].tolist(), log)
    for col in ("longName", "forwardPE", "targetMeanPrice", "recommendationKey", "numberOfAnalystOpinions", "industry", "marketCap"):
        ranked[col] = ranked["ticker"].map(enrich[col])
    # foreign filers: market cap from Yahoo when we have it
    ranked["market_cap"] = ranked["market_cap"].fillna(pd.to_numeric(ranked["marketCap"], errors="coerce"))
    ranked["upside_to_street"] = pd.to_numeric(ranked["targetMeanPrice"], errors="coerce") / ranked["price"] - 1

    out_dir = COVERAGE_DIR / "_screens" / str(today)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.concat([ranked, partial]).reset_index().to_csv(out_dir / "screen.csv", index=False)
    (out_dir / "screen.md").write_text(render_md(ranked, top, weights, min_cap, periods, len(partial)))
    log(f"Wrote {out_dir / 'screen.md'} and screen.csv")
    return out_dir


def rescore(d: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Recompute factor percentiles after foreign-filer ratios are filled in."""
    d = d.copy()
    g = d["sector"]
    fin = d["sector"].isin(["Financials", "REITs"])
    d["value"] = pd.concat([_pct(d["earnings_yield"], g), _pct(d["fcf_yield"], g), _pct(d["ebit_ev"], g)], axis=1).mean(axis=1)
    d["quality"] = pd.concat([_pct(d["roic"], g), _pct(d["op_margin"], g), _pct(d["fcf_margin"], g)], axis=1).mean(axis=1)
    d.loc[fin, "quality"] = _pct(d["roe"], g)[fin]
    d["growth"] = pd.concat([_pct(d["rev_growth"]), _pct(d["rev_growth_q"])], axis=1).mean(axis=1)
    d["momentum"] = _pct(d["mom_12_1"])
    # a missing factor counts as neutral (0.5) so missing data neither helps nor hurts a name
    d["factors_used"] = pd.DataFrame({k: d[k].notna() for k in weights}).sum(axis=1)
    parts = pd.DataFrame({k: d[k].fillna(0.5) * w for k, w in weights.items()})
    d["composite"] = (parts.sum(axis=1) / sum(weights.values())).where(d["factors_used"] > 0)
    return d


def render_md(d: pd.DataFrame, top: int, weights: dict, min_cap: float, periods: dict, n_partial: int = 0) -> str:
    L = [f"# Screen: {date.today()}",
         f"Universe: US-listed (NYSE, Nasdaq, NYSE American/CBOE incl. ADRs), market cap >= {fmt.money(min_cap)}, "
         f"price >= $5; {len(d)} companies scored. Weights: " + ", ".join(f"{k} {v:.0%}" for k, v in weights.items()) + ".",
         f"Fundamentals: SEC XBRL frames ({periods['cy']} annual, {periods['q']} quarter); foreign 20-F/40-F filers from SEC company facts (no value factor, scored neutral). "
         "Value and quality are ranked within sector; growth and momentum across the universe. "
         f"Only companies with at least 3 of 4 factors are ranked ({n_partial} held back for missing data, see screen.csv).", "",
         "| # | Ticker | Company | Sector | Mkt cap | Score | Value | Quality | Growth | Mom. | Rev gr. | Op mgn | Fwd P/E | 12-1m | Street PT | Src |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, (cik, r) in enumerate(d.head(top).iterrows(), 1):
        ln = r.get("longName")
        name = (ln if isinstance(ln, str) and ln else str(r["name"]))[:28]
        L.append(f"| {i} | {r['ticker']} | {name} | {r['sector']} | {fmt.money(r['market_cap'])} | {r['composite']:.2f} | "
                 f"{_s(r['value'])} | {_s(r['quality'])} | {_s(r['growth'])} | {_s(r['momentum'])} | "
                 f"{fmt.pct(r['rev_growth'])} | {fmt.pct(r['op_margin'])} | {fmt.multiple(_f(r.get('forwardPE')))} | "
                 f"{fmt.pct(r['mom_12_1'])} | {fmt.pct(_f(r.get('upside_to_street')))} | {r['data_source']} |")
    L += ["", "Scores are percentiles (0–1). Rev gr. = CY revenue growth (SEC) or Yahoo YoY; Street PT = upside to mean target.",
          "", "## Sector mix of the top 100", ""]
    L += [f"- {k}: {v}" for k, v in d.head(100)["sector"].value_counts().items()]
    return "\n".join(L) + "\n"


def _s(x) -> str:
    return "" if x is None or pd.isna(x) else f"{x:.2f}"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
