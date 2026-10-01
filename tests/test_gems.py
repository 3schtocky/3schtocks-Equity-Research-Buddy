"""Gems preset: period math, scoring, runway and filters (no network)."""

from datetime import date

import numpy as np
import pandas as pd

from erb import gems


def test_quarter_arithmetic():
    assert gems._prev_quarter("CY2026Q1") == "CY2025Q4"
    assert gems._prev_quarter("CY2026Q3") == "CY2026Q2"
    assert gems._year_ago("CY2026Q2") == "CY2025Q2"
    p = gems.gem_periods(date(2026, 9, 30))
    assert (p["q"], p["q_prev"], p["q1"], p["q1_prev"]) == ("CY2026Q2", "CY2025Q2", "CY2026Q1", "CY2025Q1")
    # a date whose latest filed quarter would be Q4 steps back to Q3 (Q4 lives in the 10-K)
    p = gems.gem_periods(date(2025, 4, 30))
    assert (p["q"], p["q1"]) == ("CY2024Q3", "CY2024Q2")


def _frame(**cols):
    n = len(next(iter(cols.values())))
    base = {k: [np.nan] * n for k in (
        "revenue_q", "revenue_q_prev", "revenue_q1", "revenue_q1_prev", "revenue", "revenue_prev",
        "gross_profit_q", "gross_profit_q_prev", "cogs_q", "cogs_q_prev", "op_income_q", "op_income_q_prev",
        "mom_6m")}
    base.update(cols)
    return pd.DataFrame(base, index=range(n))


def test_acceleration_beats_steady_growth():
    d = _frame(revenue_q=[140, 130, 100], revenue_q_prev=[100, 100, 100],     # 40%, 30%, 0% YoY
               revenue_q1=[110, 130, 100], revenue_q1_prev=[100, 100, 100],   # prior Q: 10%, 30%, 0%
               revenue=[480, 520, 400], revenue_prev=[400, 400, 400],
               gross_profit_q=[70, 52, 40], gross_profit_q_prev=[40, 52, 40],  # 50% vs 40%; 40% flat
               mom_6m=[0.3, 0.3, 0.0])
    s = gems.gem_score(d)
    assert s["accel"].round(2).tolist() == [0.30, 0.0, 0.0]
    assert s["margin_change"].round(2).tolist()[0] == 0.10
    assert s["composite"].idxmax() == 0   # accelerating + widening margins ranks first
    assert (s["factors_used"] == 4).all()


def test_margin_falls_back_to_cogs_then_operating_margin():
    d = _frame(revenue_q=[100, 100], revenue_q_prev=[100, 100],
               cogs_q=[40, np.nan], cogs_q_prev=[50, np.nan],
               op_income_q=[np.nan, 20], op_income_q_prev=[np.nan, 10])
    s = gems.gem_score(d)
    assert s.loc[0, "margin_basis"] == "gross" and round(s.loc[0, "margin_change"], 2) == 0.10
    assert s.loc[1, "margin_basis"] == "operating" and round(s.loc[1, "margin_change"], 2) == 0.10


def test_runway_rule_for_loss_makers():
    d = pd.DataFrame({
        "cash":              [500, 100, 50, np.nan],
        "short_investments": [100, 0, 0, np.nan],
        "cfo":               [-200, -100, 30, np.nan],   # burn 200 (3y runway), burn 100 (1y), cash-generative, unknown
        "operating_income":  [-300, -150, -10, -5],
    })
    r = gems.runway(d)
    assert r["runway_years"].round(1).tolist()[:2] == [3.0, 1.0]
    assert r["runway_ok"].tolist() == [True, False, True, False]   # unknown burn for a loss-maker fails


def test_filters():
    d = pd.DataFrame({
        "price": [10, 0.5, 10, 10, 10, 10],
        "market_cap": [1e9, 1e9, 20e9, 1e9, 1e9, 1e9],
        "adv": [10e6, 10e6, 10e6, 1e6, 10e6, 10e6],
        "listed_before_window": [True, True, True, True, False, True],
        "history_days": [800, 800, 800, 800, 200, 800],
        "runway_ok": [True, True, True, True, True, False],
    })
    kept = gems.filter_universe(d, log=lambda *_: None)
    assert kept.index.tolist() == [0]   # penny stock, too big, illiquid, recent IPO, short runway all out


def test_lumpy_milestone_quarters_are_capped_and_flagged():
    d = _frame(revenue_q=[400, 140], revenue_q_prev=[100, 100],      # +300% (milestone) vs +40%
               revenue_q1=[15, 110], revenue_q1_prev=[100, 100],     # prior quarter -85% vs +10%
               revenue=[600, 480], revenue_prev=[500, 400],
               op_income_q=[300, 20], op_income_q_prev=[-50, 10], mom_6m=[0.2, 0.2])
    s = gems.gem_score(d)
    assert s["lumpy"].tolist() == [True, False]
    assert s.loc[0, "accel"] == gems.ACCEL_CAP_LUMPY and s.loc[0, "flags"] == "lumpy revenue"
    assert abs(s.loc[0, "margin_change"]) <= gems.MARGIN_CAP_LUMPY


def test_gross_margin_jump_is_flagged_lumpy():
    d = _frame(revenue_q=[150, 150], revenue_q_prev=[100, 100], revenue_q1=[120, 120], revenue_q1_prev=[100, 100],
               gross_profit_q=[127.5, 60], gross_profit_q_prev=[20, 40])   # 85% vs 20% gross margin; 40% vs 40%
    s = gems.gem_score(d)
    assert s["lumpy"].tolist() == [True, False]
    assert s.loc[0, "margin_change"] == gems.MARGIN_CAP_LUMPY
