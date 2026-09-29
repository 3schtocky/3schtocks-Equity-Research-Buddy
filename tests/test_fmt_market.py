import pandas as pd

from erb import fmt, market


def test_house_number_style():
    assert fmt.pct(0.157) == "15.7%"
    assert fmt.pct(-0.202) == "(20.2%)"
    assert fmt.money(1.1e12) == "$1.1 tn"
    assert fmt.money(7.9e11) == "$790.0 bn"
    assert fmt.money(-8e8) == "($800.0 mn)"
    assert fmt.money(3.8e12, "TWD") == "NT$3.8 tn"
    assert fmt.multiple(25.2) == "25.2x" and fmt.multiple(-3) == "N/A"
    assert fmt.fy(2025, estimate=True) == "FY'25E" and fmt.quarter(2025, 3) == "3Q'25"


def test_yahoo_symbols():
    assert market._yf_symbol("brk.b") == "BRK-B"
    assert market._yf_symbol("SMSN.IL") == "SMSN.IL"
    assert market._yf_symbol("META") == "META"


def test_ntm_blend():
    est = {"earnings_estimate": [{"period": "0y", "avg": 10.0}, {"period": "+1y", "avg": 12.0}]}
    # half the fiscal year left -> halfway between current and next FY
    assert abs(market.ntm(est, "2026-12-31", "2026-07-02") - 11.0) < 0.02


def test_multiples_history_has_no_lookahead():
    prices = pd.DataFrame({"close": [100.0] * 30},
                          index=pd.date_range("2025-01-03", periods=30, freq="W-FRI"))
    q = pd.DataFrame({
        "end": pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]),
        "eps_diluted": [1.0, 1.0, 1.0, 1.0, 2.0], "ebitda": [10.0] * 5,
        "shares_diluted": [1.0] * 5, "net_debt": [0.0] * 5,
    }, index=["FY2024Q1", "FY2024Q2", "FY2024Q3", "FY2024Q4", "FY2025Q1"])
    filed = {"FY2024Q1": "2024-04-25", "FY2024Q2": "2024-07-25", "FY2024Q3": "2024-10-25",
             "FY2024Q4": "2025-01-30", "FY2025Q1": "2025-04-25"}
    mh = market.multiples_history(prices, q, filed)
    before = mh.loc[[d for d in mh.index if "2025-01-30" <= str(d) < "2025-04-25"], "ltm_pe"]
    after = mh.loc[[d for d in mh.index if str(d) >= "2025-04-25"], "ltm_pe"]
    assert set(before.round(6)) == {25.0}  # 100 / (1+1+1+1), once Q4'24 (the 4th quarter) was filed
    assert mh.loc[[d for d in mh.index if str(d) < "2025-01-30"], "ltm_pe"].isna().all()
    assert set(after.round(6)) == {20.0}   # 100 / (1+1+1+2), only once Q1'25 was filed
