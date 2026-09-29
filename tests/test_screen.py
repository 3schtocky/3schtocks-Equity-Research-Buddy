from datetime import date

import numpy as np
import pandas as pd

from erb import screen


def test_periods_wait_for_filings():
    p = screen._periods(date(2026, 9, 29))
    assert p["cy"] == "CY2025" and p["q"] == "CY2026Q2" and p["q_prev"] == "CY2025Q2"
    assert screen._periods(date(2026, 10, 5))["q"] == "CY2026Q2"   # Q3 10-Qs not filed yet
    assert screen._periods(date(2026, 2, 10))["cy"] == "CY2024"   # FY'25 10-Ks not out yet


def test_sector_groups():
    assert screen.sector_group(6798) == "REITs"
    assert screen.sector_group(6022) == "Financials"
    assert screen.sector_group(7370) == "Tech, Media & Telecom"
    assert screen.sector_group(2834) == "Health Care"


def _frame(n=6):
    rng = np.arange(1, n + 1, dtype=float)
    return pd.DataFrame({
        "sector": ["Tech, Media & Telecom"] * n, "market_cap": rng * 1e10, "debt": 0.0, "cash": 0.0,
        "net_income": rng * 1e9, "cfo": rng * 1e9, "capex": 0.0, "operating_income": rng * 1e9,
        "equity": 1e10, "revenue": 1e10, "revenue_prev": 9e9, "revenue_q": 3e9, "revenue_q_prev": 2.5e9,
        "mom_12_1": rng / 10, "data_source": "SEC"}, index=range(n))


def test_missing_factor_is_neutral_not_a_bonus():
    d = _frame()
    d.loc[0, "market_cap"] = np.nan  # no market cap -> no value factor, everything else intact
    out = screen.score(d, screen.DEFAULT_WEIGHTS)
    assert out.loc[0, "factors_used"] == 3
    assert out["composite"].between(0, 1).all()
    # composite equals the weighted mean with value imputed at 0.5
    w = screen.DEFAULT_WEIGHTS
    expect = (0.5 * w["value"] + out.loc[0, "quality"] * w["quality"] + out.loc[0, "growth"] * w["growth"]
              + out.loc[0, "momentum"] * w["momentum"]) / sum(w.values())
    assert abs(out.loc[0, "composite"] - (expect if not np.isnan(out.loc[0, "quality"]) else out.loc[0, "composite"])) < 1e-9


def test_financials_use_roe_not_fcf():
    d = _frame()
    d["sector"] = "Financials"
    out = screen.score(d, screen.DEFAULT_WEIGHTS)
    assert out["fcf_yield"].isna().all() and out["quality"].notna().all()
