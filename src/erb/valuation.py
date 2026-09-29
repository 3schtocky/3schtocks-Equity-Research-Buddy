"""`erb model TICKER [--init]`: draft assumptions from the facts pack, run the model, write model.json."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

from . import fmt, market, model
from .config import coverage_dir


# ---------------------------------------------------------------- loading facts

def load_facts(ticker: str) -> dict:
    d = coverage_dir(ticker) / "facts"
    if not (d / "company.json").exists():
        raise FileNotFoundError(f"No facts pack for {ticker}. Run: uv run erb facts {ticker}")
    seg_path = d / "segments.csv"
    return {
        "company": json.loads((d / "company.json").read_text()),
        "annual": pd.read_csv(d / "financials_annual.csv", index_col="period"),
        "quarterly": pd.read_csv(d / "financials_quarterly.csv", index_col="period"),
        "segments": pd.read_csv(seg_path) if seg_path.exists() and seg_path.stat().st_size > 1 else pd.DataFrame(),
        "estimates": json.loads((d / "estimates.json").read_text()),
    }


def _est(est: dict, table: str, period: str, key: str = "avg"):
    for r in est.get(table, []):
        if r.get("period") == period:
            return r.get(key)
    return None


def _clip(x, lo, hi, default):
    return default if x is None or pd.isna(x) else float(min(max(x, lo), hi))


def _last(series: pd.Series):
    s = series.dropna()
    return None if s.empty else float(s.iloc[-1])


# ---------------------------------------------------------------- init

def draft_assumptions(ticker: str) -> str:
    f = load_facts(ticker)
    c, a, q, est = f["company"], f["annual"], f["quarterly"], f["estimates"]
    m = c["market"]
    cur, trade_cur = c["financial_currency"], m.get("currency") or "USD"
    last = a.dropna(subset=["revenue"]).iloc[-1]
    base_year, base_end = int(last["fy"]), str(last["end"])[:10]
    rev0 = float(last["revenue"])
    q_valid = q.dropna(subset=["shares_diluted"]) if "shares_diluted" in q else q.iloc[0:0]
    shares = _last(q_valid["shares_diluted"]) if not q_valid.empty else float(last["shares_diluted"])
    nd_q = q["net_debt"].dropna() if "net_debt" in q else pd.Series(dtype=float)
    net_debt = float(nd_q.iloc[-1]) if not nd_q.empty else float(last.get("net_debt", 0) or 0)
    total_debt = _last(q["total_debt"]) if "total_debt" in q and q["total_debt"].notna().any() else float(last.get("total_debt") or 0)

    # Listing / FX
    listing_block = ""
    fx = 1.0
    if trade_cur != cur:
        fx = float(yf.Ticker(f"{trade_cur}{cur}=X").history(period="5d")["Close"].iloc[-1])
        # market cap (trading ccy) = price per unit x ordinary shares / shares per unit
        implied = m["price"] * shares / m["market_cap"] if m.get("market_cap") else 1.0
        ratio = round(implied) if implied >= 1 else round(implied, 2)
        listing_block = (f"listing:                      # financials in {cur}, security trades in {trade_cur}\n"
                         f"  fx_local_per_trading: {fx:.4f}   # {trade_cur}{cur}=X, Yahoo, {m['as_of']}\n"
                         f"  shares_per_unit: {ratio}          # ordinary shares per ADR, implied from market cap; VERIFY in 20-F\n"
                         f"  todo: \"Verify ADR ratio ({ratio} implied) against the depositary agreement, then delete this line.\"\n")

    # Growth path: consensus for years 1-2, then fade toward 4%
    g1 = _est(est, "revenue_estimate", "0y", "growth")
    g2 = _est(est, "revenue_estimate", "+1y", "growth")
    hist = a["revenue"].dropna()
    cagr3 = (hist.iloc[-1] / hist.iloc[-4]) ** (1 / 3) - 1 if len(hist) >= 4 and hist.iloc[-4] > 0 else 0.05
    src = "Yahoo consensus FY1/FY2, then linear fade to 4.0%"
    if g1 is None:
        g1, g2, src = cagr3, cagr3, "3-year historical CAGR (no consensus), fading to 4.0%"
    g2 = g1 if g2 is None else g2
    g1, g2 = _clip(g1, -0.3, 0.8, 0.05), _clip(g2, -0.3, 0.8, 0.05)
    fade = np.linspace(g2, 0.04, 5)[1:4]
    growth = [g1, g2, *fade]

    # Segments (only if members reconcile to consolidated revenue)
    seg_block = ""
    seg = f["segments"]
    if not seg.empty:
        s = seg[(seg["dimension"] == "segment") & (seg["concept"] == "revenue") & seg["days"].between(350, 380)]
        s = s[s["end"] == s["end"].max()] if not s.empty else s
        if len(s) >= 2 and abs(s["value"].sum() / rev0 - 1) < 0.02 and s["end"].iloc[0] == base_end:
            seg_block = "  segments:                   # from latest 10-K segment note; same growth for each until edited\n"
            for r in s.sort_values("value", ascending=False).itertuples():
                seg_block += f"    \"{r.label}\": {{base: {r.value:.0f}, growth: [{', '.join(f'{g:.3f}' for g in growth)}]}}\n"

    last3 = a.dropna(subset=["revenue"]).tail(3)
    ebitda_m = _clip(last3["ebitda_margin"].mean(), -0.5, 0.9, None) if last3["ebitda_margin"].notna().any() else None
    if ebitda_m is None:
        ebitda_m = _clip((last3["operating_margin"] + last3["d_and_a"] / last3["revenue"]).mean(), -0.5, 0.9, 0.2)
    da_pct = _clip(last["d_and_a"] / last["revenue"], 0, 0.5, 0.04)
    capex_pct = _clip(last["capex"] / last["revenue"], 0, 0.8, da_pct)
    tax = _clip(last3["tax_rate"].median(), 0.05, 0.30, 0.21)
    other = _clip((last["pretax_income"] - last["operating_income"]) / last["revenue"], -0.2, 0.2, 0.0)
    sh = a["shares_diluted"].dropna()
    share_chg = _clip((sh.iloc[-1] / sh.iloc[-4]) ** (1 / 3) - 1 if len(sh) >= 4 else 0.0, -0.05, 0.05, 0.0)
    nwc = a["current_assets"] - a["cash"].fillna(0) - a["st_investments"].fillna(0) - \
        (a["current_liabilities"] - a["debt_current"].fillna(0) - a["short_borrowings"].fillna(0))
    d_nwc, d_rev = nwc.diff().tail(3).sum(), a["revenue"].diff().tail(3).sum()
    nwc_pct = _clip(d_nwc / d_rev if d_rev else None, -0.2, 0.3, 0.05)

    # D&A: roll net PP&E forward when available, with useful life implied by the base year
    da_block = ""
    rev_path5 = rev0 * np.cumprod(1 + np.array(growth))
    capex_path5 = rev_path5 * capex_pct
    da_path = rev_path5 * da_pct
    ppe_hist = a["ppe_net"].dropna() if "ppe_net" in a else pd.Series(dtype=float)
    if len(ppe_hist) >= 2 and last["d_and_a"] and last["d_and_a"] > 0:
        ppe_prev, ppe0 = float(ppe_hist.iloc[-2]), float(ppe_hist.iloc[-1])
        cx = float(last["capex"]) if pd.notna(last["capex"]) else 0.0
        life = _clip((ppe_prev + cx / 2) / float(last["d_and_a"]), 3, 50, 10)
        da_cfg = {"ppe_base": ppe0, "useful_life": life}
        da_path = model.depreciation({"d_and_a": da_cfg}, rev_path5, capex_path5)
        da_block = (f"  d_and_a: {{ppe_base: {ppe0:.0f}, useful_life: {life:.1f}}}   "
                    f"# net PP&E roll-forward; life implied by FY{base_year} D&A (FY{base_year - 1} PP&E + half CapEx)\n")

    # Calibrate FY1-FY2 EBITDA margin so model EPS equals consensus EPS (then hold flat)
    margin_path, margin_src, eps_basis = [ebitda_m] * 5, "3-year average (EBIT + D&A) / revenue", "gaap"
    cons = [_est(est, "earnings_estimate", p) for p in ("0y", "+1y")]
    if all(cons):
        ratio_units = 1.0
        if trade_cur != cur:
            ratio_units = fx / max(round(m["price"] * shares / m["market_cap"]) if m.get("market_cap") else 1, 1)
        rev_path = rev0 * np.cumprod(1 + np.array(growth[:2]))
        sh_path = shares * np.cumprod(np.full(2, 1 + share_chg))
        solved = []
        for eps_c, rv, shs in zip(cons, rev_path, sh_path):
            eps_local = eps_c * ratio_units
            m_i = (eps_local * shs / (1 - tax) - other * rv + da_path[len(solved)]) / rv
            solved.append(m_i)
        if all(-0.5 < x < 0.95 for x in solved):
            margin_path = [solved[0], solved[1], solved[1], solved[1], solved[1]]
            margin_src = (f"FY1-FY2 solved so model EPS = consensus ({cons[0]:.2f}, {cons[1]:.2f}), then held flat. "
                          f"3-yr historical avg was {ebitda_m:.3f}")
            eps_basis = "adjusted"
        else:
            margin_src = (f"3-year average. Calibrating to consensus EPS needed an implausible margin "
                          f"({solved[0]:.2f}); check D&A, other income and the consensus basis")

    rf = float(yf.Ticker("^TNX").history(period="5d")["Close"].iloc[-1]) / 100
    beta = _clip(m.get("beta"), 0.3, 3.0, 1.0)
    int_exp = last.get("interest_expense")
    kd = _clip(int_exp / total_debt if total_debt and int_exp and not pd.isna(int_exp) else None, rf, rf + 0.05, rf + 0.015)
    mcap_local = (m.get("market_cap") or m["price"] * shares) * (fx if trade_cur != cur else 1.0)

    bands = c.get("multiple_bands") or {}
    pe_now = m.get("ntm_pe") or (bands.get("ltm_pe") or {}).get("median_1y") or 20.0
    ev_band = bands.get("ltm_ev_ebitda") or {}
    qe = q["ebitda"].dropna() if "ebitda" in q else pd.Series(dtype=float)
    ltm_ebitda = float(qe.tail(4).sum()) if len(qe) >= 4 else float(last["ebitda"])
    ev_now = (mcap_local + net_debt) / ltm_ebitda if ltm_ebitda and ltm_ebitda > 0 else None
    # Forward-on-forward: today's EV / today's NTM EBITDA (model path), applied later to NTM EBITDA at target
    fy1_end = date.fromisoformat(base_end).replace(year=int(base_end[:4]) + 1)
    r1 = min(max((fy1_end - date.fromisoformat(m["as_of"])).days / 365.25, 0), 1)
    rev12 = rev0 * np.cumprod(1 + np.array(growth[:2]))
    ntm_ebitda_now = r1 * rev12[0] * margin_path[0] + (1 - r1) * rev12[1] * margin_path[1]
    ev_fwd = (mcap_local + net_debt) / ntm_ebitda_now if ntm_ebitda_now > 0 else None
    ev_src = f"current EV / NTM EBITDA (model) = no re-rating; LTM is {ev_now:.1f}x" if ev_now else "current EV / NTM EBITDA (model)"
    ev_mult = ev_fwd or ev_now or 12.0
    exit_src = ("3-year median LTM EV/EBITDA (point-in-time); applied to FY5 EBITDA" if ev_band.get("median_3y")
                else "current forward EV/EBITDA (no LTM history); a mature exit multiple is usually lower")
    exit_mult = ev_band.get("median_3y") or ev_mult

    sic = int(c["edgar"].get("sic") or 0)
    financial = 6000 <= sic < 6800 and sic != 6798
    reit = sic == 6798
    weights_line = "{dcf: 0.50, pe: 0.25, ev_ebitda: 0.25}   # Owl-style blend; add `metric` if used"
    if financial:
        weights_line = ("{pe: 1.0}   # financial (SIC " + str(sic) + "): EBITDA/DCF not meaningful; "
                        "add P/TBV via metric_multiple and weight it")
    elif reit:
        weights_line = ("{dcf: 0.50, pe: 0.25, ev_ebitda: 0.25}   # REIT (SIC 6798): replace pe with P/FFO via "
                        "metric_multiple (FFO/share from the supplemental)")
    g_avg = float(np.mean(growth))
    g_up, g_dn = max(0.01, 0.25 * abs(g_avg)), max(0.01, 0.30 * abs(g_avg))
    m_ref = abs(margin_path[1])
    m_up, m_dn = 0.10 * m_ref, 0.15 * m_ref
    dps = m.get("dividend_rate") or 0.0

    peers_hint = "[]   # TODO: 4-6 peers, e.g. [GOOG, SNAP, PINS, RDDT]"
    return f"""# {c['name']} ({c['ticker']}) valuation assumptions. Drafted by `erb model --init` on {date.today()}.
# Every default below is a starting point from filings/market data; edit with reasons (see comments).
# Currency: {cur} (financials). Per-share values are per ordinary share unless `listing` converts them.
ticker: {c['ticker']}
as_of: {m['as_of']}                  # price date (previous close)
price: {m['price']:.2f}                    # {trade_cur}, Yahoo
horizon_months: 15                  # 12-18 month horizon
base_year: {base_year}                     # last reported fiscal year (10-K/20-F)
base_fiscal_year_end: {base_end}
projection_years: 5
eps_basis: {eps_basis}                 # gaap | adjusted. Calibrated to consensus => adjusted basis (Street EPS usually excludes one-offs; some firms also exclude SBC)
shares_diluted: {shares:.0f}        # latest diluted weighted shares, 10-Q/10-K
net_debt: {net_debt:.0f}            # latest total debt - cash - ST investments ({cur}); negative = net cash
dividend_per_share: {dps:.2f}              # annual, per traded unit, {trade_cur} (Yahoo)
{listing_block}
revenue:
  base: {rev0:.0f}                 # FY{base_year} revenue ({cur})
  growth: [{', '.join(f'{g:.3f}' for g in growth)}]   # {src}
{seg_block}
margins:
  ebitda_margin: [{', '.join(f'{x:.3f}' for x in margin_path)}]   # {margin_src}
  d_and_a_pct_rev: {da_pct:.3f}          # FY{base_year}; used only if `d_and_a` below is removed
{da_block}  capex_pct_rev: {capex_pct:.3f}            # FY{base_year}; update from management CapEx guidance
  tax_rate: {tax:.3f}                 # median effective rate, last 3 years (clipped 5-30%)
  other_income_pct_rev: {other:.3f}     # (pretax - operating income) / revenue, FY{base_year}
  share_change: {share_chg:.3f}            # annual change in diluted shares (3-year CAGR)
  nwc_pct_delta_rev: {nwc_pct:.3f}       # change in net working capital per $ of revenue growth (3-year)

wacc:
  risk_free: {rf:.4f}               # 10Y UST yield (^TNX), {m['as_of']}
  beta: {beta:.2f}                    # Yahoo 5Y monthly beta
  erp: 0.045                        # equity risk premium: Ethan to confirm (Damodaran implied ERP is a common source)
  cost_of_debt_pretax: {kd:.4f}     # interest expense / total debt, FY{base_year} (bounded rf to rf+5%)
  tax_rate: 0.21                    # statutory, for the debt tax shield
  equity_value: {mcap_local:.0f}     # market cap ({cur})
  debt_value: {total_debt or 0:.0f}       # total debt ({cur})

terminal:
  method: exit_multiple             # exit_multiple | perpetuity
  exit_ev_ebitda: {exit_mult:.1f}            # {exit_src}
  perpetual_growth: 0.030           # used for perpetuity method and cross-checks

multiples:                          # target multiples applied to NTM metrics at the target date
  forward_pe: {pe_now:.1f}                # current NTM P/E (consensus); re-rating needs a reason
  ev_ebitda: {ev_mult:.1f}                 # {ev_src}

# Optional for REITs / banks: P/FFO, P/TBV etc. per_share values by projected year
# metric_multiple: {{name: P/FFO, per_share: [..5 values..], multiple: 20.0}}

weights: {weights_line}

scenarios:                          # deltas vs base; defaults scale with this company's growth (25-30%) and margin (10-15%)
  bull: {{growth_delta: {g_up:.3f}, margin_delta: {m_up:.3f}, multiple_delta: 0.10, wacc_delta: -0.005}}
  bear: {{growth_delta: {-g_dn:.3f}, margin_delta: {-m_dn:.3f}, multiple_delta: -0.15, wacc_delta: 0.005}}

benchmark:
  sp500_expected_return: 0.08       # annual; Ethan to confirm. Rating uses the horizon-scaled value
  band: 0.05                        # Outperform/Underperform threshold (percentage points)

peers: {peers_hint}
eps_actual_overrides: {{}}           # e.g. {{"FY2025Q3": 7.25}} to show adjusted actuals on the cover table
"""


# ---------------------------------------------------------------- comps

COMP_FIELDS = {
    "name": "longName", "price": "currentPrice", "market_cap": "marketCap", "enterprise_value": "enterpriseValue",
    "revenue_growth": "revenueGrowth", "earnings_growth": "earningsGrowth", "gross_margin": "grossMargins",
    "ebitda_margin": "ebitdaMargins", "operating_margin": "operatingMargins", "net_margin": "profitMargins",
    "ev_sales": "enterpriseToRevenue", "ev_ebitda": "enterpriseToEbitda", "pe_ltm": "trailingPE",
    "pe_ntm": "forwardPE", "roe": "returnOnEquity", "roa": "returnOnAssets", "debt_to_equity": "debtToEquity",
    "beta": "beta", "dividend_rate": "dividendRate", "current_ratio": "currentRatio", "quick_ratio": "quickRatio",
    "currency": "currency", "financial_currency": "financialCurrency",
}


def comps(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for t in tickers:
        info = yf.Ticker(market._yf_symbol(t)).info or {}
        row = {"ticker": t.upper(), **{k: info.get(v) for k, v in COMP_FIELDS.items()}}
        if row["debt_to_equity"] is not None:
            row["debt_to_equity"] = row["debt_to_equity"] / 100  # Yahoo reports percent
        if row["dividend_rate"] and row["price"]:
            row["dividend_yield"] = row["dividend_rate"] / row["price"]
        if row["currency"] != row["financial_currency"]:
            row["ev_sales"] = row["ev_ebitda"] = None  # Yahoo mixes currencies for ADRs
        rows.append(row)
    return pd.DataFrame(rows).set_index("ticker")


MULTIPLE_COLS = ("ev_sales", "ev_ebitda", "pe_ltm", "pe_ntm")


def comp_stats(df: pd.DataFrame, subject: str) -> dict:
    """High/mean/median/low across peers (subject excluded; negative multiples are N/A)."""
    peers = df.drop(index=subject, errors="ignore")
    num = peers.select_dtypes("number").copy()
    for col in MULTIPLE_COLS:
        if col in num:
            num[col] = num[col].where(num[col] > 0)
    return {stat: num.agg(stat).replace({np.nan: None}).to_dict() for stat in ("max", "mean", "median", "min")}


# ---------------------------------------------------------------- cover EPS table

def eps_table(f: dict, a: dict, proj: pd.DataFrame) -> dict:
    q = f["quarterly"]
    overrides = a.get("eps_actual_overrides") or {}
    base_year = int(a["base_year"])
    # Seasonality: operating income share by quarter, averaged over the last two full years
    # (net income is distorted by one-offs such as tax charges); falls back to revenue, then equal
    weights = np.full(4, 0.25)
    for col in ("operating_income", "revenue"):
        full = [fy for fy in sorted(q["fy"].unique())
                if (q["fy"] == fy).sum() == 4 and q.loc[q["fy"] == fy, col].notna().all()][-2:]
        shares_by_year = []
        for fy in full:
            v = q[q["fy"] == fy].sort_values("q")[col].to_numpy(dtype=float)
            if v.sum() > 0 and (v > 0).all():
                shares_by_year.append(v / v.sum())
        if shares_by_year:
            weights = np.mean(shares_by_year, axis=0)
            break

    def actual(fy, qn):
        key = f"FY{fy}Q{qn}"
        if key in overrides:
            return float(overrides[key]), "actual (adjusted override)"
        if key in q.index and pd.notna(q.loc[key, "eps_diluted"]):
            return float(q.loc[key, "eps_diluted"]), "actual"
        return None, None

    table = {}
    for fy in (base_year, base_year + 1, base_year + 2):
        model_fy = float(proj.loc[fy, "eps"]) if fy in proj.index else None
        acts = [actual(fy, i) for i in range(1, 5)]
        if fy == base_year:
            vals = [v for v, _ in acts]
            kinds = [k for _, k in acts]
            year_total = sum(vals) if all(v is not None for v in vals) else None
        else:
            known = sum(v for v, _ in acts if v is not None)
            rem_idx = [i for i, (v, _) in enumerate(acts) if v is None]
            rem_w = weights[rem_idx].sum() if rem_idx else 1
            rem_total = (model_fy - known) if model_fy is not None else None
            vals, kinds = [], []
            for i, (v, k) in enumerate(acts):
                if v is not None:
                    vals.append(v)
                    kinds.append(k)
                else:
                    vals.append(rem_total * weights[i] / rem_w if rem_total is not None else None)
                    kinds.append("estimate")
            year_total = model_fy
        table[f"FY{fy}"] = {"quarters": vals, "kinds": kinds, "year": year_total}
    fys = list(table)
    for i, fy in enumerate(fys[1:], 1):
        prev = table[fys[i - 1]]
        table[fy]["yoy_quarters"] = [(v / p - 1) if v is not None and p and p > 0 else None
                                     for v, p in zip(table[fy]["quarters"], prev["quarters"])]
        table[fy]["yoy_year"] = (table[fy]["year"] / prev["year"] - 1) if table[fy]["year"] and prev["year"] else None
    mixed = a.get("eps_basis") == "adjusted" and not overrides
    return {"basis": a.get("eps_basis", "gaap"), "seasonality": weights.tolist(), "years": table,
            "note": ("Actual quarters are GAAP (filings) while estimates are on the adjusted/consensus basis; "
                     "set eps_actual_overrides with adjusted actuals from the earnings releases.") if mixed else None}


# ---------------------------------------------------------------- run

def _jsonable(obj):
    if isinstance(obj, pd.DataFrame):
        return obj.reset_index().to_dict("records")
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, (date, pd.Timestamp)):
        return str(obj)[:10]
    raise TypeError(type(obj))


def run(ticker: str, log=print) -> dict:
    cdir = coverage_dir(ticker)
    path = cdir / "assumptions.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No assumptions for {ticker}. Run: uv run erb model {ticker} --init")
    a = yaml.safe_load(path.read_text())
    f = load_facts(ticker)
    c, m = f["company"], f["company"]["market"]
    out = model.run(a)
    res = out["results"]
    base = res["base"]
    proj = base["projections"]

    # model vs consensus sanity check (years 1-2)
    vs = {}
    for i, period in enumerate(("0y", "+1y")):
        fy = int(a["base_year"]) + 1 + i
        if fy in proj.index:
            cons_eps = _est(f["estimates"], "earnings_estimate", period)
            cons_rev = _est(f["estimates"], "revenue_estimate", period)
            eps_listing = model._listing(a, proj.loc[fy, "eps"])
            vs[f"FY{fy}"] = {"model_revenue": proj.loc[fy, "revenue"], "consensus_revenue": cons_rev,
                             "model_eps": eps_listing, "consensus_eps": cons_eps,
                             "eps_diff": (eps_listing / cons_eps - 1) if cons_eps else None}

    for fy, v in vs.items():
        if v["eps_diff"] is not None and abs(v["eps_diff"]) > 0.10:
            out["warnings"].append(f"{fy} model EPS is {v['eps_diff']:+.0%} vs consensus; make sure the gap is a deliberate call.")
            break

    peers = a.get("peers") or []
    comp_df, stats = pd.DataFrame(), {}
    if peers:
        comp_df = comps([ticker, *peers])
        for col in MULTIPLE_COLS:
            comp_df[col] = comp_df[col].where(comp_df[col] > 0)
        comp_df.to_csv(cdir / "comps.csv")
        stats = comp_stats(comp_df, ticker.upper())

    # football field (per traded unit)
    sens = out["sensitivity"]
    flat = [v for row in sens["values"] for v in row]
    ff = {"52-week range": [m["week52_low"], m["week52_high"]],
          "Street price targets": [m.get("target_low"), m.get("target_high")],
          "DCF sensitivity": [min(flat), max(flat)],
          "Scenario range": [res["bear"]["price_target"], res["bull"]["price_target"]]}
    if peers and base["ntm_eps_at_target"]:
        pe = comp_df.drop(index=ticker.upper(), errors="ignore")["pe_ntm"].dropna()
        if len(pe) >= 2:
            ff["Peer NTM P/E (25th-75th pct)"] = [model._listing(a, pe.quantile(.25) * base["ntm_eps_at_target"]),
                                                   model._listing(a, pe.quantile(.75) * base["ntm_eps_at_target"])]
        ev = comp_df.drop(index=ticker.upper(), errors="ignore")["ev_ebitda"].dropna()
        if len(ev) >= 2 and base["ntm_ebitda_at_target"]:
            conv = lambda x: model._listing(a, (x * base["ntm_ebitda_at_target"] - a["net_debt"]) / a["shares_diluted"])
            ff["Peer EV/EBITDA (25th-75th pct)"] = [conv(ev.quantile(.25)), conv(ev.quantile(.75))]

    last = f["annual"].dropna(subset=["revenue"]).iloc[-1]
    ntm_ebitda_now = model.ntm_at(proj, "ebitda", date.fromisoformat(str(a["as_of"])))
    ev_now = a["wacc"]["equity_value"] + a["net_debt"]
    cover = {"price": a["price"], "as_of": a["as_of"], "exchange": m.get("exchange"),
             "week52_low": m["week52_low"], "week52_high": m["week52_high"], "ytd_return": m["ytd_return"],
             "market_cap": m.get("market_cap"), "dividend_yield": m.get("dividend_yield"),
             "ntm_pe": m.get("ntm_pe"), "ntm_ev_ebitda": ev_now / ntm_ebitda_now if ntm_ebitda_now else None,
             "roe": last.get("roe"), "roa": last.get("roa"),
             "roic": last.get("roic"), "currency": m.get("currency")}

    result = {
        "ticker": ticker.upper(), "name": c["name"], "generated": date.today().isoformat(),
        "assumptions": a, "rating": out["rating"], "warnings": out["warnings"],
        "price": a["price"], "horizon_months": a.get("horizon_months", 15),
        "scenarios": {s: {k: v for k, v in r.items() if k != "projections"} for s, r in res.items()},
        "projections": {s: r["projections"] for s, r in res.items()},
        "sensitivity": sens, "football_field": ff, "consensus_check": vs,
        "comps": comp_df.reset_index().replace({np.nan: None}).to_dict("records") if not comp_df.empty else [],
        "comp_stats": stats, "cover": cover, "eps_table": eps_table(f, a, proj),
    }
    if result["eps_table"]["note"]:
        result["warnings"].append(result["eps_table"]["note"])
    (cdir / "model.json").write_text(json.dumps(result, indent=2, default=_jsonable))
    for s in model.SCENARIOS:
        res[s]["projections"].to_csv(cdir / f"projections_{s}.csv")
    log(summary(result))
    return result


def summary(r: dict) -> str:
    cur = r["cover"]["currency"] or "USD"
    L = [f"{r['name']} ({r['ticker']}) @ {fmt.price(r['price'], cur)}  ->  {r['rating']['rating'].upper()}"]
    for s in ("bear", "base", "bull"):
        sc = r["scenarios"][s]
        meth = ", ".join(f"{k} {fmt.price(v, cur)}" for k, v in sc["methods"].items())
        L.append(f"  {s:>4}: PT {fmt.price(sc['price_target'], cur)} ({fmt.pct(sc['price_return'])} price, "
                 f"{fmt.pct(sc['total_return'])} total) | WACC {fmt.pct(sc['wacc']['wacc'])} | {meth}")
    rt = r["rating"]
    L.append(f"  S&P 500 expected over {rt['horizon_months']} mo: {fmt.pct(rt['benchmark_return'])}; "
             f"excess {fmt.pct(rt['excess_return'])} (band ±{rt['band'] * 100:.0f} pts)")
    for fy, v in r["consensus_check"].items():
        if v["consensus_eps"]:
            L.append(f"  {fy} EPS model {fmt.price(v['model_eps'], cur)} vs consensus {fmt.price(v['consensus_eps'], cur)} "
                     f"({fmt.pct(v['eps_diff'])})")
    d = r["scenarios"]["base"]["dcf"]
    L.append(f"  DCF: TV {fmt.pct(d['tv_share_of_ev'])} of EV; implied perpetual growth {fmt.pct(d['implied_perpetual_growth'])}")
    L += [f"  WARNING: {w}" for w in r["warnings"]]
    return "\n".join(L)
