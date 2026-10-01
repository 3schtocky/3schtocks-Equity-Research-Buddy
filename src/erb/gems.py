"""`erb screen --preset gems`: small and mid caps at an inflection.

Hunts for businesses whose growth is speeding up (in the spirit of early Eos Energy or Rambus):

Universe
- US-listed (NYSE, Nasdaq, NYSE American/CBOE incl. ADRs), market cap $0.3-15 bn, price >= $1,
  average daily traded value >= $5 mn (90 days).
- Recent IPOs (under a year of trading history) are excluded.
- Loss-makers are allowed only if cash covers at least 2 years of operating cash burn.

Factors (percentile ranks across the Gems universe; higher is better)
- acceleration (35%): latest quarter's revenue growth YoY minus the prior quarter's YoY
- growth (25%): latest quarter YoY and calendar-year revenue growth
- margin (20%): gross margin change, latest quarter vs the same quarter a year earlier
  (operating margin change when gross profit isn't reported)
- momentum (20%): 6-month price return
A name needs at least 3 of the 4 factors; a missing factor counts as neutral (0.5).

`as_of` runs the screen as of a past date using only quarters whose filings would have been out
(45-day lag) and prices up to that date. Caveats for such checks: today's listed universe
(survivorship bias); SEC frames hold the latest filed value for each period (restatements); and
Yahoo prices are adjusted for later splits while SEC share counts are as filed, so market cap
(and the $1 floor) can be off for names that split after the date. The known-winner check
corrects this for the names it reports on.

Catalysts: for the finalists, recent 8-K material events from SEC submissions (free).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from . import edgar, fmt, market
from .config import CACHE_DIR, COVERAGE_DIR
from .screen import EXCHANGES, REV_TAGS, _first, _instant, _pct, _periods, sector_group, sic_codes

GEM_WEIGHTS = {"acceleration": 0.35, "growth": 0.25, "margin": 0.20, "momentum": 0.20}
MIN_CAP, MAX_CAP = 0.3e9, 15e9
MIN_ADV = 5e6
MIN_PRICE = 1.0
MIN_RUNWAY_YEARS = 2.0
IPO_DAYS = 365
# Lumpy revenue (licensing milestones, one big order): a quarter that swings from deep decline to
# triple-digit growth, or a huge margin jump, is a one-off rather than an inflection. Such names
# keep their place in the list but their acceleration and margin signals are capped.
LUMPY_PRIOR_YOY = -0.5
LUMPY_YOY = 2.0
LUMPY_MARGIN = 0.5
ACCEL_CAP_LUMPY = 0.25
MARGIN_CAP_LUMPY = 0.15
COMMODITY_SICS = {1311, 1381, 1382, 1389, 2911, 4412, 4424, 4922, 4923, 1000, 1040, 1090, 1220, 1221}
GP_TAGS = ["GrossProfit"]
COGS_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]

# 8-K items worth a look when hunting catalysts (and one warning sign).
ITEMS_8K = {
    "1.01": "Material agreement", "1.02": "Agreement terminated", "2.01": "Acquisition or disposal",
    "2.03": "New financing obligation", "3.02": "Unregistered share sale (dilution)",
    "5.02": "Officer or director change", "7.01": "Reg FD disclosure", "8.01": "Other material event",
}


# ---- periods -----------------------------------------------------------------------------
def _prev_quarter(label: str) -> str:
    """'CY2026Q2' -> 'CY2026Q1'; 'CY2026Q1' -> 'CY2025Q4'."""
    y, q = int(label[2:6]), int(label[-1])
    return f"CY{y - 1}Q4" if q == 1 else f"CY{y}Q{q - 1}"


def _year_ago(label: str) -> str:
    return f"CY{int(label[2:6]) - 1}Q{label[-1]}"


def gem_periods(as_of: date) -> dict:
    """Latest two filed quarters. Fourth quarters are skipped: companies report Q4 inside the
    annual 10-K, so stand-alone Q4 values are sparse in SEC frames (most names would drop out)."""
    p = _periods(as_of)
    q = p["q"]
    if q.endswith("Q4"):
        q = _prev_quarter(q)
    q1 = _prev_quarter(q)
    return {**p, "q": q, "q_prev": _year_ago(q), "q1": q1, "q1_prev": _year_ago(q1)}


# ---- data --------------------------------------------------------------------------------
def gem_fundamentals(periods: dict, log=print) -> pd.DataFrame:
    log(f"SEC frames: quarters {periods['q']} and {periods['q1']} vs a year earlier; {periods['cy']} annual")
    rev = {k: _first(REV_TAGS, periods[k], "max") for k in ("q", "q_prev", "q1", "q1_prev", "cy", "cy_prev")}
    gp = {k: _first(GP_TAGS, periods[k]) for k in ("q", "q_prev")}
    cogs = {k: _first(COGS_TAGS, periods[k], "max") for k in ("q", "q_prev")}
    op = {k: _first(["OperatingIncomeLoss"], periods[k]) for k in ("q", "q_prev")}
    f = pd.DataFrame({
        "revenue_q": rev["q"], "revenue_q_prev": rev["q_prev"],
        "revenue_q1": rev["q1"], "revenue_q1_prev": rev["q1_prev"],
        "revenue": rev["cy"], "revenue_prev": rev["cy_prev"],
        "gross_profit_q": gp["q"], "gross_profit_q_prev": gp["q_prev"],
        "cogs_q": cogs["q"], "cogs_q_prev": cogs["q_prev"],
        "op_income_q": op["q"], "op_income_q_prev": op["q_prev"],
        "operating_income": _first(["OperatingIncomeLoss"], periods["cy"]),
        "cfo": _first(["NetCashProvidedByUsedInOperatingActivities"], periods["cy"]),
        "shares": _first(["WeightedAverageNumberOfDilutedSharesOutstanding"], periods["q"], unit="shares")
        .combine_first(_first(["WeightedAverageNumberOfDilutedSharesOutstanding"], periods["cy"], unit="shares")),
        "cash": _instant(["CashAndCashEquivalentsAtCarryingValue",
                          "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], periods["inst"]),
        "short_investments": _instant(["ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
                                      periods["inst"]),
    })
    f.index.name = "cik"
    return f


CHUNK = 200
CHUNK_PAUSE = 2.0          # seconds between batches: Yahoo throttles bursts
RETRY_WAITS = (30, 90, 240)  # seconds before each retry round for tickers that failed
MIN_COVERAGE = 0.90        # never cache a download missing more than 10% of tickers


def _download(symbols: list[str], start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = yf.download(symbols, start=start.isoformat(), end=end.isoformat(), auto_adjust=True,
                     progress=False, threads=True)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        return df["Close"], df["Volume"]
    return (df[["Close"]].rename(columns={"Close": symbols[0]}),
            df[["Volume"]].rename(columns={"Volume": symbols[0]}))


def prices_as_of(tickers: list[str], as_of: date, log=print,
                 refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """About 13 months of adjusted closes and volumes ending at `as_of`.

    Downloads in throttled batches, retries tickers Yahoo rate-limited, and caches the result
    only when coverage is complete enough to rank against (a partial universe would distort
    every percentile)."""
    import time as _time

    path = CACHE_DIR / f"gems_prices_{as_of}.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    symbols = {market._yf_symbol(t): t for t in tickers}
    start, end = as_of - timedelta(days=400), as_of + timedelta(days=1)
    settled = False   # True once retries stop recovering tickers (the rest didn't trade then)
    closes, vols = [], []
    todo = list(symbols)
    for attempt in range(len(RETRY_WAITS) + 1):
        failed = []
        chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
        for i, chunk in enumerate(chunks, 1):
            log(f"Yahoo prices {i}/{len(chunks)} (to {as_of}){' retry ' + str(attempt) if attempt else ''}")
            c, v = _download(chunk, start, end)
            got = set(c.columns[c.notna().any()]) if not c.empty else set()
            failed += [s for s in chunk if s not in got]
            if not c.empty:
                closes.append(c[list(got)])
                vols.append(v[list(got)])
            _time.sleep(CHUNK_PAUSE)
        # Retry while retries still recover a meaningful share; tickers that didn't trade yet (or
        # are gone) never come back, and for a past date they are the norm, not a failure.
        if attempt and len(todo) - len(failed) < 0.02 * len(todo):
            settled = True
        if not failed or len(failed) < 0.02 * len(symbols) or settled or attempt == len(RETRY_WAITS):
            settled = settled or not failed or len(failed) < 0.02 * len(symbols)
            break
        log(f"{len(failed)} tickers missing (rate limits?); retrying in {RETRY_WAITS[attempt]}s")
        _time.sleep(RETRY_WAITS[attempt])
        todo = failed
    px = pd.concat(closes, axis=1).rename(columns=symbols) if closes else pd.DataFrame()
    vol = pd.concat(vols, axis=1).rename(columns=symbols) if vols else pd.DataFrame()
    px, vol = px.loc[:, ~px.columns.duplicated()], vol.loc[:, ~vol.columns.duplicated()]
    coverage = px.shape[1] / max(len(symbols), 1)
    log(f"Price coverage {coverage:.0%} of {len(symbols)} tickers")
    if coverage >= MIN_COVERAGE or settled:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pd.to_pickle((px, vol), path)
    else:
        log(f"Coverage below {MIN_COVERAGE:.0%}: not caching; percentiles from this run are less reliable")
    return px, vol


def market_fields(df: pd.DataFrame, px: pd.DataFrame, vol: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Price, market cap, liquidity, 6-month momentum and trading history as of the date."""
    d = df.copy()
    px = px[px.index <= pd.Timestamp(as_of)]
    vol = vol[vol.index <= pd.Timestamp(as_of)]
    last = px.ffill().iloc[-1]
    d["price"] = d["ticker"].map(last)
    recent = px.index[-1] - pd.Timedelta(days=90)
    adv = (px[px.index >= recent] * vol[vol.index >= recent]).mean()
    d["adv"] = d["ticker"].map(adv)
    ago6 = px.index[-1] - pd.Timedelta(days=182)
    p6 = px[px.index <= ago6].ffill().iloc[-1] if (px.index <= ago6).any() else px.bfill().iloc[0]
    d["mom_6m"] = d["ticker"].map(last / p6 - 1)
    first_trade = px.apply(lambda s: s.first_valid_index())
    d["first_trade"] = d["ticker"].map(first_trade)
    window_start = px.index[0]
    # A name whose first trade is well after the start of the price window listed recently.
    d["history_days"] = (pd.Timestamp(as_of) - pd.to_datetime(d["first_trade"])).dt.days
    d["listed_before_window"] = pd.to_datetime(d["first_trade"]) <= window_start + pd.Timedelta(days=10)
    d["market_cap"] = d["price"] * d["shares"]
    return d


# ---- scoring -----------------------------------------------------------------------------
def gem_score(df: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    weights = weights or GEM_WEIGHTS
    d = df.copy()
    pos = lambda s: s.where(s > 0)   # noqa: E731
    d["yoy_q"] = (d["revenue_q"] / pos(d["revenue_q_prev"]) - 1).clip(-0.9, 3)
    d["yoy_q1"] = (d["revenue_q1"] / pos(d["revenue_q1_prev"]) - 1).clip(-0.9, 3)
    d["rev_growth"] = (d["revenue"] / pos(d["revenue_prev"]) - 1).clip(-0.9, 3)
    d["accel"] = d["yoy_q"] - d["yoy_q1"]

    gp_q = d["gross_profit_q"].combine_first(d["revenue_q"] - d["cogs_q"])
    gp_prev = d["gross_profit_q_prev"].combine_first(d["revenue_q_prev"] - d["cogs_q_prev"])
    d["gross_margin_q"] = gp_q / pos(d["revenue_q"])
    d["gross_margin_q_prev"] = gp_prev / pos(d["revenue_q_prev"])
    d["gm_change"] = d["gross_margin_q"] - d["gross_margin_q_prev"]
    om_change = d["op_income_q"] / pos(d["revenue_q"]) - d["op_income_q_prev"] / pos(d["revenue_q_prev"])
    d["margin_change"] = d["gm_change"].combine_first(om_change)   # raw: the lumpy test needs it unclipped
    d["margin_basis"] = np.where(d["gm_change"].notna(), "gross", np.where(om_change.notna(), "operating", ""))

    lumpy = ((d["yoy_q1"] < LUMPY_PRIOR_YOY) | (d["yoy_q"] > LUMPY_YOY)
             | (d["margin_change"].abs() > LUMPY_MARGIN)).fillna(False)
    d["lumpy"] = lumpy
    d.loc[lumpy, "accel"] = d.loc[lumpy, "accel"].clip(upper=ACCEL_CAP_LUMPY)
    d.loc[lumpy, "margin_change"] = d.loc[lumpy, "margin_change"].clip(-MARGIN_CAP_LUMPY, MARGIN_CAP_LUMPY)
    d["margin_change"] = d["margin_change"].clip(-0.5, 0.5)   # keep extreme values from dominating ties
    sic = d["sic"] if "sic" in d else pd.Series(0, index=d.index)
    sector = d["sector"] if "sector" in d else pd.Series("", index=d.index)
    commodity = sic.isin(COMMODITY_SICS) | sector.eq("Energy & Mining")
    d["flags"] = [", ".join(f for f, on in (("lumpy revenue", lu), ("commodity-driven", co)) if on)
                  for lu, co in zip(lumpy, commodity, strict=True)]

    d["acceleration"] = _pct(d["accel"])
    d["growth"] = pd.concat([_pct(d["yoy_q"]), _pct(d["rev_growth"])], axis=1).mean(axis=1)
    d["margin"] = _pct(d["margin_change"])
    d["momentum"] = _pct(d["mom_6m"])
    d["factors_used"] = pd.DataFrame({k: d[k].notna() for k in weights}).sum(axis=1)
    parts = pd.DataFrame({k: d[k].fillna(0.5) * w for k, w in weights.items()})
    d["composite"] = (parts.sum(axis=1) / sum(weights.values())).where(d["factors_used"] > 0)
    return d


def runway(df: pd.DataFrame) -> pd.DataFrame:
    """Cash runway for cash burners: (cash + short-term investments) / annual operating burn."""
    d = df.copy()
    liquid = d["cash"].fillna(0) + d["short_investments"].fillna(0)
    burning = d["cfo"] < 0
    d["cash_burn"] = (-d["cfo"]).where(burning)
    d["runway_years"] = (liquid / d["cash_burn"]).where(burning)
    loss = (d["operating_income"] < 0) | burning
    # A loss-maker passes only with a measured runway of at least MIN_RUNWAY_YEARS; profitable
    # companies (or loss-makers generating operating cash) pass.
    d["runway_ok"] = ~loss | (~burning & d["cfo"].notna()) | (d["runway_years"] >= MIN_RUNWAY_YEARS)
    d["loss_maker"] = loss
    return d


def filter_universe(d: pd.DataFrame, log=print) -> pd.DataFrame:
    steps = [
        ("price >= $1", d["price"] >= MIN_PRICE),
        ("market cap $0.3-15 bn", d["market_cap"].between(MIN_CAP, MAX_CAP)),
        ("ADV >= $5 mn", d["adv"] >= MIN_ADV),
        ("listed at least a year", d["listed_before_window"] & (d["history_days"] >= IPO_DAYS)),
        ("loss-makers need 2+ years of cash", d["runway_ok"]),
    ]
    keep = pd.Series(True, index=d.index)
    for label, cond in steps:
        keep &= cond.fillna(False)
        log(f"  {label}: {int(keep.sum())} left")
    return d[keep]


# ---- catalysts ---------------------------------------------------------------------------
def recent_8k(cik: int, as_of: date, days: int = 90) -> list[dict]:
    """Material 8-K events filed in the `days` before `as_of` (from SEC submissions)."""
    try:
        sub = edgar.submissions(int(cik))
    except Exception:
        return []
    r = sub.get("filings", {}).get("recent", {})
    out = []
    since = as_of - timedelta(days=days)
    for form, filed, items, acc, doc in zip(r.get("form", []), r.get("filingDate", []), r.get("items", []),
                                            r.get("accessionNumber", []), r.get("primaryDocument", []), strict=False):
        if form not in ("8-K", "8-K/A"):
            continue
        d = date.fromisoformat(filed)
        if not since <= d <= as_of:
            continue
        codes = [c.strip() for c in str(items or "").split(",") if c.strip() in ITEMS_8K]
        if not codes:
            continue
        out.append({"filed": filed, "items": [f"{c} {ITEMS_8K[c]}" for c in codes],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"})
    return out


# ---- run ---------------------------------------------------------------------------------
def build(as_of: date | None = None, log=print, keep_all: bool = False, refresh: bool = False):
    """The scored, filtered Gems universe as of a date (today by default). With `keep_all`, also
    returns every company before the filters (to explain why a name didn't make it)."""
    as_of = as_of or date.today()
    periods = gem_periods(as_of)
    universe = pd.DataFrame([vars(c) for c in edgar.all_tickers()])
    universe = universe[universe["exchange"].isin(EXCHANGES)]
    universe = universe[~universe["ticker"].str.contains(r"-(?:W|WT|U|R|P[A-Z]?)$|\.(?:W|U|R)$", regex=True)]
    universe = universe.drop_duplicates("cik")
    log(f"Universe: {len(universe)} companies")
    df = universe.set_index("cik").join(gem_fundamentals(periods, log), how="left")
    px, vol = prices_as_of(df["ticker"].tolist(), as_of, log, refresh=refresh)
    df = market_fields(df, px, vol, as_of)
    df = runway(df)
    before = df.copy()
    log("Filters:")
    df = filter_universe(df, log)
    info = sic_codes(df.index.tolist(), log)
    df["sic"] = df.index.map(lambda c: info[c][0])
    df["sector"] = df["sic"].map(sector_group)
    scored = gem_score(df)
    ranked = scored[scored["factors_used"] >= 3].sort_values("composite", ascending=False)
    ranked["rank"] = range(1, len(ranked) + 1)
    log(f"Ranked {len(ranked)} Gems candidates (at least 3 of 4 factors)")
    return (ranked, before) if keep_all else ranked


def run(top: int = 30, finalists: int = 25, as_of: date | None = None, log=print,
        refresh: bool = False) -> Path:
    as_of = as_of or date.today()
    ranked = build(as_of, log, refresh=refresh)
    log(f"8-K events for the top {finalists}")
    signals = {}
    for cik, r in ranked.head(finalists).iterrows():
        signals[r["ticker"]] = recent_8k(cik, as_of)
    out_dir = COVERAGE_DIR / "_screens" / f"{as_of}-gems"
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked.reset_index().to_csv(out_dir / "screen.csv", index=False)
    (out_dir / "signals.json").write_text(json.dumps(signals, indent=1))
    (out_dir / "screen.md").write_text(render_md(ranked, top, as_of, signals))
    log(f"Wrote {out_dir / 'screen.md'}, screen.csv and signals.json")
    return out_dir


def render_md(d: pd.DataFrame, top: int, as_of: date, signals: dict) -> str:
    w = ", ".join(f"{k} {v:.0%}" for k, v in GEM_WEIGHTS.items())
    L = [f"# Gems screen: {as_of}",
         f"Small and mid caps at an inflection. Market cap {fmt.money(MIN_CAP)}-{fmt.money(MAX_CAP)}, ADV >= "
         f"{fmt.money(MIN_ADV)}, price >= ${MIN_PRICE:.0f}, listed at least a year, loss-makers only with "
         f">= {MIN_RUNWAY_YEARS:.0f} years of cash. {len(d)} companies ranked. Weights: {w}.", "",
         "| # | Ticker | Company | Sector | Mkt cap | Score | Accel | Growth | Margin | Mom. | Q YoY | Prior Q YoY | "
         "Margin chg | 6m | Runway | 8-K events (90d) | Flags |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in d.head(top).iterrows():
        ev = signals.get(r["ticker"], [])
        runway_txt = f"{r['runway_years']:.1f}y" if pd.notna(r.get("runway_years")) else ("profitable" if not r["loss_maker"] else "cash-generative")
        L.append(f"| {r['rank']} | {r['ticker']} | {str(r['name'])[:26]} | {r['sector']} | {fmt.money(r['market_cap'])} | "
                 f"{r['composite']:.2f} | {_s(r['acceleration'])} | {_s(r['growth'])} | {_s(r['margin'])} | "
                 f"{_s(r['momentum'])} | {fmt.pct(r['yoy_q'])} | {fmt.pct(r['yoy_q1'])} | "
                 f"{_pts(r['margin_change'])} {r['margin_basis']} | {fmt.pct(r['mom_6m'])} | {runway_txt} | {len(ev)} | "
                 f"{r.get('flags') or ''} |")
    L += ["", "Scores are percentiles (0-1) within the Gems universe. Accel = latest-quarter YoY growth minus the prior "
          "quarter's. Margin chg in percentage points vs the same quarter a year earlier. Flags: lumpy revenue "
         "(one-off swings; acceleration and margin signals capped), commodity-driven (prices, not the business).", "",
          "## Recent 8-K events (finalists)", ""]
    for t, evs in signals.items():
        if evs:
            L.append(f"- **{t}**: " + "; ".join(f"{e['filed']} {', '.join(e['items'])}" for e in evs[:5]))
    return "\n".join(L) + "\n"


def _s(x) -> str:
    return "" if x is None or pd.isna(x) else f"{x:.2f}"


def _pts(x) -> str:
    return "" if x is None or pd.isna(x) else f"{x * 100:+.1f} pts"


# ---- known-winner check ------------------------------------------------------------------------
def check_known_winners(cases: list[tuple[str, date]], log=print) -> list[dict]:
    """Where did known winners rank in Gems as of a date before their run, and what happened next?"""
    out = []
    for ticker, as_of in cases:
        ranked, before = build(as_of, log=lambda *_: None, keep_all=True)
        factor = split_factor(ticker, as_of)
        if factor != 1.0:   # price is adjusted for later splits; put shares on the same basis
            log(f"{ticker}: splits after {as_of} (x{factor:g}); market cap corrected for the check")
            before.loc[before["ticker"] == ticker, "market_cap"] *= factor
        row = ranked[ranked["ticker"] == ticker]
        fwd = forward_return(ticker, as_of, 365)
        spy = forward_return("SPY", as_of, 365)
        if row.empty:
            out.append({"ticker": ticker, "as_of": str(as_of), "ranked": False, "universe": len(ranked),
                        "why_not": why_not(before, ticker), "forward_12m": fwd, "spy_12m": spy})
            continue
        r = row.iloc[0]
        out.append({"ticker": ticker, "as_of": str(as_of), "ranked": True, "rank": int(r["rank"]),
                    "universe": len(ranked), "percentile": round(1 - (r["rank"] - 1) / len(ranked), 3),
                    "score": round(float(r["composite"]), 3), "yoy_q": _num(r["yoy_q"]),
                    "accel": _num(r["accel"]), "margin_change": _num(r["margin_change"]),
                    "mom_6m": _num(r["mom_6m"]), "forward_12m": fwd, "spy_12m": spy})
        log(f"{ticker} as of {as_of}: rank {int(r['rank'])} of {len(ranked)}")
    return out


def why_not(before: pd.DataFrame, ticker: str) -> list[str]:
    """The filters a ticker failed (or 'too little data to score')."""
    r = before[before["ticker"] == ticker]
    if r.empty:
        return ["not in the listed universe (no SEC ticker or exchange)"]
    r = r.iloc[0]
    reasons = []
    if not (r.get("price") or 0) >= MIN_PRICE:
        reasons.append(f"price {r.get('price')}")
    if not MIN_CAP <= (r.get("market_cap") or 0) <= MAX_CAP:
        reasons.append(f"market cap {fmt.money(r.get('market_cap'))}")
    if not (r.get("adv") or 0) >= MIN_ADV:
        reasons.append(f"liquidity {fmt.money(r.get('adv'))}/day")
    if not (bool(r.get("listed_before_window")) and (r.get("history_days") or 0) >= IPO_DAYS):
        reasons.append("listed under a year")
    if not bool(r.get("runway_ok")):
        rw = r.get("runway_years")
        reasons.append(f"cash runway {rw:.1f} years (needs {MIN_RUNWAY_YEARS:.0f})" if pd.notna(rw)
                       else "loss-maker with unknown cash burn")
    return reasons or ["passed the filters but had fewer than 3 of 4 factors (missing quarterly data)"]


def split_factor(ticker: str, after: date) -> float:
    """Product of stock splits after a date (e.g. 10.0 for a later 10-for-1)."""
    try:
        s = yf.Ticker(market._yf_symbol(ticker)).splits
        s = s[s.index.tz_localize(None) > pd.Timestamp(after)] if len(s) else s
        return float(np.prod(s.values)) if len(s) else 1.0
    except Exception:
        return 1.0


def forward_return(ticker: str, start: date, days: int) -> float | None:
    end = start + timedelta(days=days)
    try:
        px = yf.download(market._yf_symbol(ticker), start=start.isoformat(), end=(end + timedelta(days=5)).isoformat(),
                         auto_adjust=True, progress=False)["Close"]
        px = px.squeeze() if hasattr(px, "squeeze") else px
        return round(float(px.iloc[-1] / px.iloc[0] - 1), 4)
    except Exception:
        return None


def _num(x):
    return None if x is None or pd.isna(x) else round(float(x), 4)
