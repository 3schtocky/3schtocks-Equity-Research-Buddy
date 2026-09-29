"""Valuation model: assumptions.yaml -> projections, DCF, multiples, scenarios, rating.

The LLM never computes these numbers. It edits assumptions (with reasons) and
reads model.json.

Conventions
- Internal values are in the company's financial currency, per ordinary share.
  `listing` converts to the traded security (ADR ratio, FX) for price targets.
- DCF: unlevered FCF = EBIT x (1 - t) + D&A - CapEx - change in NWC. Only the
  remaining fraction of the current fiscal year counts (stub), with mid-period
  discounting. Terminal value comes from an exit EV/EBITDA multiple or
  perpetuity growth. Today's value is rolled forward at the cost of equity to
  the target date, less dividends.
- Multiples: target multiple x next-twelve-months metric as of the target date.
- Scenarios apply deltas to growth (every year), margins (ramped to the full
  delta by the final year), multiples (% change) and WACC.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SCENARIOS = ("bear", "base", "bull")


def _vec(x, n: int) -> np.ndarray:
    """Scalar or list -> length-n array (short lists repeat their last value)."""
    if isinstance(x, (int, float)):
        return np.full(n, float(x))
    arr = [float(v) for v in x]
    return np.array((arr + [arr[-1]] * n)[:n])


def _years_between(a: date, b: date) -> float:
    return (b - a).days / 365.25


def _fy_end(fiscal_year_end: date, fy_offset: int) -> date:
    y = fiscal_year_end.year + fy_offset
    try:
        return fiscal_year_end.replace(year=y)
    except ValueError:  # Feb 29
        return fiscal_year_end.replace(year=y, day=28)


@dataclass
class Scenario:
    growth_delta: float = 0.0
    margin_delta: float = 0.0
    multiple_delta: float = 0.0  # fractional change, e.g. +0.10 = multiples 10% higher
    wacc_delta: float = 0.0
    growth_path: list | None = None  # optional absolute revenue growth by year (e.g. a cyclical downturn); replaces base growth


def scenario(a: dict, name: str) -> Scenario:
    return Scenario(**(a.get("scenarios", {}).get(name) or {})) if name != "base" else Scenario()


# ---------------------------------------------------------------- projections

def depreciation(m: dict, revenue: np.ndarray, capex: np.ndarray) -> np.ndarray:
    """D&A path. `d_and_a: {ppe_base, useful_life}` rolls net PP&E forward
    (D&A = (opening PP&E + half of the year's CapEx) / life), so depreciation
    catches up with heavy investment. Otherwise D&A is `d_and_a_pct_rev` x revenue."""
    cfg = m.get("d_and_a")
    if not cfg:
        return revenue * _vec(m["d_and_a_pct_rev"], len(revenue))
    ppe, life = float(cfg["ppe_base"]), float(cfg["useful_life"])
    out = []
    for cx in capex:
        da = (ppe + cx / 2) / life
        ppe = ppe + cx - da
        out.append(da)
    return np.array(out)


def project(a: dict, sc: Scenario) -> pd.DataFrame:
    n = int(a["projection_years"])
    base_year = int(a["base_year"])
    fye0 = date.fromisoformat(str(a["base_fiscal_year_end"]))
    years = [base_year + i for i in range(1, n + 1)]
    rev_cfg, m = a["revenue"], a["margins"]

    segs = rev_cfg.get("segments") or {"Total": {"base": rev_cfg["base"], "growth": rev_cfg["growth"]}}
    seg_rev = {}
    for name, cfg in segs.items():
        g = (_vec(sc.growth_path, n) if sc.growth_path is not None else _vec(cfg["growth"], n)) + sc.growth_delta
        seg_rev[name] = float(cfg["base"]) * np.cumprod(1 + g)
    revenue = sum(seg_rev.values())
    base_rev = sum(float(c["base"]) for c in segs.values())

    ramp = np.arange(1, n + 1) / n
    ebitda_margin = _vec(m["ebitda_margin"], n) + sc.margin_delta * ramp
    ebitda = revenue * ebitda_margin
    capex = revenue * _vec(m["capex_pct_rev"], n)
    da = depreciation(m, revenue, capex)
    ebit = ebitda - da
    other = revenue * _vec(m.get("other_income_pct_rev", 0.0), n)
    pretax = ebit + other
    tax_rate = _vec(m["tax_rate"], n)
    net_income = pretax * (1 - tax_rate)
    shares = float(a["shares_diluted"]) * np.cumprod(1 + _vec(m.get("share_change", 0.0), n))
    eps = net_income / shares
    prev_rev = np.concatenate([[base_rev], revenue[:-1]])
    d_nwc = (revenue - prev_rev) * _vec(m.get("nwc_pct_delta_rev", 0.0), n)
    ufcf = ebit * (1 - tax_rate) + da - capex - d_nwc

    df = pd.DataFrame({
        "fy": years,
        "fy_end": [_fy_end(fye0, i) for i in range(1, n + 1)],
        "revenue": revenue, "revenue_growth": revenue / prev_rev - 1,
        "ebitda": ebitda, "ebitda_margin": ebitda_margin, "d_and_a": da, "ebit": ebit,
        "ebit_margin": ebit / revenue, "other_income": other, "pretax_income": pretax,
        "tax_rate": tax_rate, "net_income": net_income, "shares_diluted": shares, "eps": eps,
        "capex": capex, "d_nwc": d_nwc, "ufcf": ufcf, "fcf_margin": ufcf / revenue,
    })
    for name, vals in seg_rev.items():
        if name != "Total":
            df[f"seg:{name}"] = vals
    return df.set_index("fy")


# ---------------------------------------------------------------- discount rate

def wacc(a: dict, sc: Scenario) -> dict:
    w = a["wacc"]
    ke = w["risk_free"] + w["beta"] * w["erp"]
    kd = w["cost_of_debt_pretax"] * (1 - w.get("tax_rate", 0.21))
    e, d = float(w["equity_value"]), float(w["debt_value"])
    we = e / (e + d) if e + d else 1.0
    value = we * ke + (1 - we) * kd + sc.wacc_delta
    return {"cost_of_equity": ke + sc.wacc_delta, "cost_of_debt_after_tax": kd, "weight_equity": we,
            "weight_debt": 1 - we, "wacc": value}


# ---------------------------------------------------------------- valuation

def _listing(a: dict, per_share_local: float) -> float:
    """Local-currency value per ordinary share -> value per traded unit (e.g. ADR, in USD)."""
    lst = a.get("listing") or {}
    return per_share_local * float(lst.get("shares_per_unit", 1.0)) / float(lst.get("fx_local_per_trading", 1.0))


def dcf(a: dict, proj: pd.DataFrame, rates: dict, exit_multiple: float | None = None,
        growth: float | None = None) -> dict:
    as_of = date.fromisoformat(str(a["as_of"]))
    r = rates["wacc"]
    t_cfg = a["terminal"]
    method = t_cfg.get("method", "exit_multiple")
    exit_multiple = exit_multiple if exit_multiple is not None else t_cfg.get("exit_ev_ebitda")
    growth = growth if growth is not None else t_cfg.get("perpetual_growth", 0.025)

    pv, t_prev_end = 0.0, 0.0
    rows = []
    for fy, row in proj.iterrows():
        end_t = _years_between(as_of, row["fy_end"])
        if end_t <= 0:
            continue
        start_t = max(t_prev_end, end_t - 1.0)
        frac = end_t - start_t  # < 1 for the stub (current) year
        cf = row["ufcf"] * frac
        t_mid = (start_t + end_t) / 2
        disc = (1 + r) ** -t_mid
        pv += cf * disc
        rows.append({"fy": fy, "fraction": frac, "ufcf": cf, "t": t_mid, "discount": disc, "pv": cf * disc})
        t_prev_end = end_t
    last = proj.iloc[-1]
    n_t = t_prev_end
    if method == "exit_multiple":
        tv = exit_multiple * last["ebitda"]
    else:
        tv = last["ufcf"] * (1 + growth) / (r - growth)
    pv_tv = tv * (1 + r) ** -n_t
    ev = pv + pv_tv
    equity = ev - float(a["net_debt"])
    per_share = equity / float(a["shares_diluted"])

    # cross-checks between terminal methods
    implied_g = (tv * r - last["ufcf"]) / (tv + last["ufcf"]) if method == "exit_multiple" else growth
    implied_multiple = tv / last["ebitda"] if last["ebitda"] > 0 else None
    return {"method": method, "pv_cash_flows": pv, "terminal_value": tv, "pv_terminal": pv_tv,
            "enterprise_value": ev, "equity_value": equity, "value_per_share_local": per_share,
            "tv_share_of_ev": pv_tv / ev if ev else None, "implied_perpetual_growth": implied_g,
            "implied_exit_multiple": implied_multiple, "exit_multiple": exit_multiple,
            "perpetual_growth": growth, "schedule": rows}


def ntm_at(proj: pd.DataFrame, col: str, when: date) -> float | None:
    """Twelve months forward from `when`, blending fiscal years by time."""
    ends = list(proj["fy_end"])
    for i, end in enumerate(ends):
        if end >= when:
            if i + 1 >= len(ends):
                return None
            r = min((end - when).days / 365.25, 1.0)
            return r * proj[col].iloc[i] + (1 - r) * proj[col].iloc[i + 1]
    return None


def value_scenario(a: dict, name: str) -> dict:
    sc = scenario(a, name)
    proj = project(a, sc)
    rates = wacc(a, sc)
    as_of = date.fromisoformat(str(a["as_of"]))
    h = float(a.get("horizon_months", 15)) / 12
    target_date = as_of + timedelta(days=round(h * 365.25))
    mult = a["multiples"]
    k = 1 + sc.multiple_delta
    shares, net_debt = float(a["shares_diluted"]), float(a["net_debt"])
    price = float(a["price"])
    dps = float(a.get("dividend_per_share", 0.0))  # per traded unit, trading currency

    exit_mult = a["terminal"].get("exit_ev_ebitda")
    d = dcf(a, proj, rates, exit_multiple=exit_mult * k if exit_mult else None)
    methods = {}
    dcf_today = _listing(a, d["value_per_share_local"])
    methods["dcf"] = dcf_today * (1 + rates["cost_of_equity"]) ** h - dps * h

    ntm_eps = ntm_at(proj, "eps", target_date)
    ntm_ebitda = ntm_at(proj, "ebitda", target_date)
    if mult.get("forward_pe") and ntm_eps:
        methods["pe"] = _listing(a, mult["forward_pe"] * k * ntm_eps)
    if mult.get("ev_ebitda") and ntm_ebitda:
        methods["ev_ebitda"] = _listing(a, (mult["ev_ebitda"] * k * ntm_ebitda - net_debt) / shares)
    metric = a.get("metric_multiple")
    if metric and metric.get("multiple"):
        per_share = pd.Series(_vec(metric["per_share"], len(proj)), index=proj.index)
        tmp = proj.assign(_metric=per_share.values)
        v = ntm_at(tmp, "_metric", target_date)
        if v:
            methods["metric"] = _listing(a, metric["multiple"] * k * v)

    weights = {m: float(w) for m, w in (a.get("weights") or {}).items() if m in methods and w}
    total_w = sum(weights.values())
    pt = sum(methods[m] * w for m, w in weights.items()) / total_w if total_w else methods["dcf"]
    price_return = pt / price - 1
    total_return = price_return + dps * h / price
    return {"scenario": name, "deltas": vars(sc), "wacc": rates, "dcf": d, "methods": methods,
            "weights": {m: w / total_w for m, w in weights.items()} if total_w else {"dcf": 1.0},
            "price_target": pt, "price_return": price_return, "total_return": total_return,
            "target_date": target_date.isoformat(), "ntm_eps_at_target": ntm_eps,
            "ntm_ebitda_at_target": ntm_ebitda, "projections": proj}


def rating(a: dict, base_total_return: float) -> dict:
    b = a.get("benchmark") or {}
    annual = float(b.get("sp500_expected_return", 0.08))
    band = float(b.get("band", 0.05))
    h = float(a.get("horizon_months", 15)) / 12
    bench = (1 + annual) ** h - 1
    diff = base_total_return - bench
    label = "Outperform" if diff > band else "Underperform" if diff < -band else "Neutral"
    return {"rating": label, "benchmark_return": bench, "sp500_expected_annual": annual,
            "band": band, "excess_return": diff, "horizon_months": a.get("horizon_months", 15)}


def sensitivity(a: dict, wacc_steps=(-0.01, -0.005, 0.0, 0.005, 0.01), mult_steps=(-2, -1, 0, 1, 2),
                g_steps=(-0.01, -0.005, 0.0, 0.005, 0.01)) -> dict:
    """Base-case DCF price target: WACC (rows) vs exit multiple or perpetual growth (columns)."""
    method = a["terminal"].get("method", "exit_multiple")
    h = float(a.get("horizon_months", 15)) / 12
    dps = float(a.get("dividend_per_share", 0.0))
    base = Scenario()
    proj = project(a, base)
    rates0 = wacc(a, base)
    cols = ([a["terminal"]["exit_ev_ebitda"] + s for s in mult_steps] if method == "exit_multiple"
            else [a["terminal"].get("perpetual_growth", 0.025) + s for s in g_steps])
    grid = []
    for dw in wacc_steps:
        rates = dict(rates0, wacc=rates0["wacc"] + dw)
        row = []
        for c in cols:
            d = dcf(a, proj, rates, exit_multiple=c if method == "exit_multiple" else None,
                    growth=c if method != "exit_multiple" else None)
            row.append(_listing(a, d["value_per_share_local"]) * (1 + rates0["cost_of_equity"]) ** h - dps * h)
        grid.append(row)
    return {"rows_wacc": [rates0["wacc"] + dw for dw in wacc_steps], "cols": cols,
            "col_label": "Exit EV/EBITDA" if method == "exit_multiple" else "Perpetual growth", "values": grid}


def checks(a: dict, results: dict) -> list[str]:
    warn = []
    base = results["base"]
    d = base["dcf"]
    if d["tv_share_of_ev"] and d["tv_share_of_ev"] > 0.85:
        warn.append(f"Terminal value is {d['tv_share_of_ev']:.0%} of DCF EV; near-term cash flows carry little weight.")
    g = d["implied_perpetual_growth"]
    if g is not None and (g > 0.045 or g < 0):
        warn.append(f"Exit multiple implies {g:.1%} perpetual growth; justify or lower the multiple.")
    if base["wacc"]["wacc"] <= (a["terminal"].get("perpetual_growth", 0.025) + 0.02):
        warn.append("WACC is within 2 points of terminal growth; DCF is unstable.")
    pts = [results[s]["price_target"] for s in SCENARIOS]
    if not (pts[0] <= pts[1] <= pts[2]):
        warn.append("Scenario price targets are not ordered bear <= base <= bull; check scenario deltas.")
    used = {k: v for k, v in base["methods"].items() if k in base["weights"]}
    if len(used) > 1:
        spread = max(used.values()) / max(min(used.values()), 1e-9)
        if spread > 1.5 or min(used.values()) <= 0:
            warn.append(f"Weighted methods disagree by {spread:.1f}x ({', '.join(f'{k} {v:,.0f}' for k, v in used.items())}).")
    first = base["projections"].iloc[0]
    if abs(first["revenue_growth"]) > 0.6:
        warn.append(f"First projected year revenue growth is {first['revenue_growth']:.0%}; check the base year.")
    lst = a.get("listing") or {}
    if lst.get("todo"):
        warn.append(lst["todo"])
    return warn


def run(a: dict) -> dict:
    a = copy.deepcopy(a)
    results = {s: value_scenario(a, s) for s in SCENARIOS}
    rate = rating(a, results["base"]["total_return"])
    return {"results": results, "rating": rate, "sensitivity": sensitivity(a), "warnings": checks(a, results)}
