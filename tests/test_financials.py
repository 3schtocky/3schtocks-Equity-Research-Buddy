from datetime import date

from erb import financials as fin


def row(start, end, val, accn, filed, form="10-Q", fy=2024, fp="Q1"):
    r = {"end": end, "val": val, "accn": accn, "filed": filed, "form": form, "fy": fy, "fp": fp}
    if start:
        r["start"] = start
    return r


def company_facts():
    """FY2024 (calendar). Revenue reported as discrete quarters; cash flow only as YTD."""
    rev = [
        row("2024-01-01", "2024-03-31", 100, "q1", "2024-04-25", fp="Q1"),
        row("2024-04-01", "2024-06-30", 110, "q2", "2024-07-25", fp="Q2"),
        row("2024-07-01", "2024-09-30", 120, "q3", "2024-10-25", fp="Q3"),
        row("2024-01-01", "2024-12-31", 460, "k", "2025-02-01", form="10-K", fp="FY"),
        # restated Q1 in the next year's 10-Q: value should update, first_filed should not
        row("2024-01-01", "2024-03-31", 101, "q1b", "2025-04-25", fy=2025, fp="Q1"),
        row("2025-01-01", "2025-03-31", 130, "q1b", "2025-04-25", fy=2025, fp="Q1"),
    ]
    cfo = [
        row("2024-01-01", "2024-03-31", 30, "q1", "2024-04-25", fp="Q1"),
        row("2024-01-01", "2024-06-30", 70, "q2", "2024-07-25", fp="Q2"),
        row("2024-01-01", "2024-09-30", 100, "q3", "2024-10-25", fp="Q3"),
        row("2024-01-01", "2024-12-31", 150, "k", "2025-02-01", form="10-K", fp="FY"),
    ]
    assets = [row(None, "2024-12-31", 1000, "k", "2025-02-01", form="10-K", fp="FY"),
              row(None, "2024-09-30", 900, "q3", "2024-10-25", fp="Q3")]
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": rev}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": cfo}},
        "Assets": {"units": {"USD": assets}},
    }}}


def test_quarters_from_discrete_ytd_and_q4_derivation():
    r = fin.build(company_facts())
    q = r["quarterly"]
    # Revenue Q4 = FY - (Q1..Q3), using the restated Q1 (101)
    assert q.loc["FY2024Q4", "revenue"] == 460 - (101 + 110 + 120)
    # CFO quarters from YTD differences
    assert list(q.loc[["FY2024Q1", "FY2024Q2", "FY2024Q3", "FY2024Q4"], "cfo"]) == [30, 40, 30, 50]
    assert r["provenance"]["cfo|FY2024Q2"]["derived"] is True
    assert r["provenance"]["revenue|FY2024Q1"]["derived"] is False


def test_restatement_keeps_first_filed_for_point_in_time():
    r = fin.build(company_facts())
    p = r["provenance"]["revenue|FY2024Q1"]
    assert p["filed"] == "2025-04-25"        # latest value wins
    assert p["first_filed"] == "2024-04-25"  # but it was public since the original 10-Q


def test_annual_and_instant_items():
    r = fin.build(company_facts())
    a = r["annual"]
    assert a.loc["FY2024", "revenue"] == 460
    assert a.loc["FY2024", "total_assets"] == 1000
    assert r["quarterly"].loc["FY2024Q3", "total_assets"] == 900
    assert a.loc["FY2024", "end"] == date(2024, 12, 31)


def test_open_fiscal_year_quarters():
    q = fin.build(company_facts())["quarterly"]
    assert q.loc["FY2025Q1", "revenue"] == 130
    assert q.loc["FY2025Q1", "revenue_yoy"] == 130 / 101 - 1


def test_tag_priority_latest_data_leads():
    cf = company_facts()
    cf["facts"]["us-gaap"]["SalesRevenueNet"] = {"units": {"USD": [
        row("2020-01-01", "2020-12-31", 5, "old", "2021-02-01", form="10-K", fy=2020, fp="FY")]}}
    series, _ = fin.select_series(cf["facts"], "revenue", {"us-gaap": ["SalesRevenueNet", "Revenues"]}, instant=False)
    # Revenues has later data so it leads; the old tag only fills its gap year
    assert series[(date(2024, 1, 1), date(2024, 12, 31))].tag == "us-gaap:Revenues"
    assert series[(date(2020, 1, 1), date(2020, 12, 31))].tag == "us-gaap:SalesRevenueNet"
