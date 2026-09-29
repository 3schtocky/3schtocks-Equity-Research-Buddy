"""Model math against hand calculations."""
import copy
from datetime import date

import pytest

from erb import model

BASE = {
    "as_of": "2024-12-31", "price": 50.0, "horizon_months": 15, "base_year": 2024,
    "base_fiscal_year_end": "2024-12-31", "projection_years": 2,
    "shares_diluted": 10, "net_debt": 0, "dividend_per_share": 0,
    "revenue": {"base": 100, "growth": 0.10},
    "margins": {"ebitda_margin": 0.50, "d_and_a_pct_rev": 0.10, "capex_pct_rev": 0.10,
                "tax_rate": 0.20, "other_income_pct_rev": 0.0, "share_change": 0.0, "nwc_pct_delta_rev": 0.0},
    "wacc": {"risk_free": 0.05, "beta": 1.0, "erp": 0.05, "cost_of_debt_pretax": 0.06, "tax_rate": 0.21,
             "equity_value": 500, "debt_value": 0},
    "terminal": {"method": "exit_multiple", "exit_ev_ebitda": 10.0, "perpetual_growth": 0.03},
    "multiples": {"forward_pe": 20.0, "ev_ebitda": 10.0},
    "weights": {"dcf": 1.0},
    "scenarios": {"bull": {"growth_delta": 0.05, "margin_delta": 0.05, "multiple_delta": 0.1},
                  "bear": {"growth_delta": -0.05, "margin_delta": -0.05, "multiple_delta": -0.1}},
    "benchmark": {"sp500_expected_return": 0.08, "band": 0.05},
}


def a(**over):
    x = copy.deepcopy(BASE)
    for k, v in over.items():
        x[k] = v
    return x


def test_projection_by_hand():
    p = model.project(a(), model.Scenario())
    assert p.loc[2025, "revenue"] == pytest.approx(110)
    assert p.loc[2025, "ebit"] == pytest.approx(44)          # 55 - 11
    assert p.loc[2025, "eps"] == pytest.approx(3.52)         # 44 * 0.8 / 10
    assert p.loc[2025, "ufcf"] == pytest.approx(35.2)        # 44*0.8 + 11 - 11
    assert p.loc[2026, "eps"] == pytest.approx(3.872)
    assert p.loc[2026, "fy_end"] == date(2026, 12, 31)


def test_dcf_by_hand():
    x = a()
    p = model.project(x, model.Scenario())
    d = model.dcf(x, p, model.wacc(x, model.Scenario()))
    # ~10% WACC, mid-year: 35.2/1.1^0.5 + 38.72/1.1^1.5 + (10 x 60.5)/1.1^2 = 33.56 + 33.56 + 500.0
    assert d["enterprise_value"] == pytest.approx(567.12, rel=2e-3)
    assert d["value_per_share_local"] == pytest.approx(56.71, rel=2e-3)
    v = model.value_scenario(x, "base")
    assert v["price_target"] == pytest.approx(56.71 * 1.1 ** 1.25, rel=3e-3)  # rolled forward at Ke


def test_stub_year_counts_only_remaining_fraction():
    x = a(as_of="2025-07-02")
    p = model.project(x, model.Scenario())
    d = model.dcf(x, p, model.wacc(x, model.Scenario()))
    first = d["schedule"][0]
    assert first["fraction"] == pytest.approx(0.5, abs=0.01)
    assert first["ufcf"] == pytest.approx(35.2 * first["fraction"])


def test_pe_method_uses_ntm_at_target_date():
    x = a(projection_years=3, weights={"pe": 1.0})
    v = model.value_scenario(x, "base")
    # target ~2026-04-01: NTM = r * FY26 EPS + (1-r) * FY27 EPS with r ~ 0.75
    r = (date(2026, 12, 31) - date.fromisoformat(v["target_date"])).days / 365.25
    ntm = r * 3.872 + (1 - r) * 4.2592
    assert v["methods"]["pe"] == pytest.approx(20 * ntm, rel=1e-6)
    assert v["price_target"] == pytest.approx(20 * ntm, rel=1e-6)


def test_scenarios_ordered_and_rating_thresholds():
    x = a(projection_years=3, weights={"dcf": 0.5, "pe": 0.25, "ev_ebitda": 0.25})
    out = model.run(x)
    pts = [out["results"][s]["price_target"] for s in model.SCENARIOS]
    assert pts[0] < pts[1] < pts[2]
    bench = 1.08 ** 1.25 - 1
    assert model.rating(x, bench + 0.051)["rating"] == "Outperform"
    assert model.rating(x, bench + 0.049)["rating"] == "Neutral"
    assert model.rating(x, bench - 0.051)["rating"] == "Underperform"


def test_adr_listing_conversion():
    x = a(listing={"fx_local_per_trading": 32.0, "shares_per_unit": 5})
    assert model._listing(x, 64.0) == pytest.approx(10.0)  # NT$64/share x 5 shares / 32 NT$ per $


def test_ppe_rollforward_depreciation():
    import numpy as np
    da = model.depreciation({"d_and_a": {"ppe_base": 100, "useful_life": 10}},
                            np.array([1.0, 1.0]), np.array([20.0, 20.0]))
    assert da[0] == pytest.approx(11.0)            # (100 + 10) / 10
    assert da[1] == pytest.approx((109 + 10) / 10)  # PP&E 100 + 20 - 11 = 109


def test_perpetuity_cross_check():
    x = a(terminal={"method": "perpetuity", "perpetual_growth": 0.03, "exit_ev_ebitda": 10})
    p = model.project(x, model.Scenario())
    d = model.dcf(x, p, model.wacc(x, model.Scenario()))
    assert d["terminal_value"] == pytest.approx(38.72 * 1.03 / (0.10 - 0.03), rel=1e-3)
