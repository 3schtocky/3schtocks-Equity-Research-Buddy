"""Build standardized annual and quarterly financial statements from EDGAR company facts.

Every value carries provenance (XBRL tag, accession number, filing date, and
whether it was derived), so any figure in a report can be traced to a filing.

Quarterly logic:
- Discrete three-month facts are used when reported.
- Otherwise a quarter is year-to-date minus the prior year-to-date (10-Q cash flow
  statements only report cumulative figures).
- Q4 is the fiscal year minus nine-month year-to-date, and is marked derived.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .xbrl_map import FLOW, INSTANT, PER_SHARE, SHARE_COUNT

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}
PERIODIC_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A", "6-K", "6-K/A"}
TOL = timedelta(days=4)


@dataclass
class Fact:
    tag: str
    start: date | None
    end: date
    val: float
    accn: str
    filed: str
    form: str
    fy: int | None
    fp: str | None
    first_filed: str = ""  # when this period's figure was first public (for point-in-time use)

    @property
    def days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days + 1


def _parse(tag: str, raw: dict) -> Fact:
    return Fact(
        tag=tag,
        start=date.fromisoformat(raw["start"]) if "start" in raw else None,
        end=date.fromisoformat(raw["end"]),
        val=float(raw["val"]),
        accn=raw["accn"],
        filed=raw["filed"],
        form=raw.get("form", ""),
        fy=raw.get("fy"),
        fp=raw.get("fp"),
    )


def _pick_unit(units: dict, item: str) -> str | None:
    """Choose the unit for an item: per-share, share count, or the most recent currency."""
    if item in PER_SHARE:
        cands = [u for u in units if "/shares" in u]
    elif item in SHARE_COUNT:
        cands = [u for u in units if u == "shares"]
    else:
        cands = [u for u in units if "/" not in u and u not in ("shares", "pure")]
    if not cands:
        return None
    return max(cands, key=lambda u: max(r["end"] for r in units[u]))


def _tag_series(facts: dict, taxonomy: str, tag: str, item: str, instant: bool) -> tuple[dict, str | None]:
    """All facts for one tag, deduped by period (latest filing wins, so restatements apply)."""
    node = facts.get(taxonomy, {}).get(tag)
    if not node:
        return {}, None
    unit = _pick_unit(node["units"], item)
    if unit is None:
        return {}, None
    series: dict = {}
    first: dict = {}
    for raw in node["units"][unit]:
        if raw.get("form") not in PERIODIC_FORMS:
            continue
        f = _parse(f"{taxonomy}:{tag}", raw)
        if instant != (f.start is None):
            continue
        key = f.end if instant else (f.start, f.end)
        first[key] = min(first.get(key, f.filed), f.filed)
        if key not in series or f.filed > series[key].filed:
            series[key] = f
    for key, f in series.items():
        f.first_filed = first[key]
    return series, unit


def select_series(facts: dict, item: str, spec: dict, instant: bool) -> tuple[dict, str | None]:
    """Merge candidate tags: the tag with the latest data leads, the others fill gaps."""
    per_tag = []
    for taxonomy, tags in spec.items():
        for priority, tag in enumerate(tags):
            series, unit = _tag_series(facts, taxonomy, tag, item, instant)
            if series:
                latest = max((k if instant else k[1]) for k in series)
                per_tag.append((latest, -priority, series, unit))
    if not per_tag:
        return {}, None
    per_tag.sort(key=lambda t: (t[0], t[1]), reverse=True)
    merged = dict(per_tag[0][2])
    unit = per_tag[0][3]
    for _, _, series, u in sorted(per_tag[1:], key=lambda t: -t[1]):
        if u != unit:
            continue
        for k, f in series.items():
            merged.setdefault(k, f)
    return merged, unit


def fiscal_years(flow_series: list[dict], fy_map: dict) -> list[tuple[date, date, int]]:
    """Fiscal year periods (start, end, fy label) from annual-duration facts."""
    periods: dict[date, date] = {}
    for series in flow_series:
        for (s, e), f in series.items():
            if 350 <= (f.days or 0) <= 380:
                periods.setdefault(e, s)
    out = []
    for e, s in sorted(periods.items(), key=lambda kv: kv[0]):
        if out and abs(out[-1][1] - e) <= TOL:
            continue
        out.append((s, e, _fy_label(e, fy_map)))
    return out


def _fy_label(end: date, fy_map: dict) -> int:
    for (e, fp), fy in fy_map.items():
        if fp == "FY" and abs(e - end) <= TOL:
            return fy
    return end.year


def build_fy_map(facts: dict) -> dict:
    """Map (period end, fp) -> fiscal year, from each filing's own reporting period."""
    by_accn: dict[str, list] = {}
    for taxonomy in ("us-gaap", "ifrs-full"):
        for tag in ("NetIncomeLoss", "ProfitLoss", "Revenues", "Assets", "Revenue",
                    "RevenueFromContractWithCustomerExcludingAssessedTax"):
            node = facts.get(taxonomy, {}).get(tag)
            if not node:
                continue
            for rows in node["units"].values():
                for r in rows:
                    by_accn.setdefault(r["accn"], []).append(r)
    fy_map = {}
    for rows in by_accn.values():
        end = max(r["end"] for r in rows)
        own = [r for r in rows if r["end"] == end and r.get("fy") and r.get("fp")]
        if own:
            fy_map[(date.fromisoformat(end), own[0]["fp"])] = own[0]["fy"]
    return fy_map


def _quarterize(series: dict, fs: date, fe: date | None, annual: Fact | None, additive: bool):
    """Return {q: (value, [facts], derived)} for one fiscal year."""
    horizon = fe or fs + timedelta(days=366)
    inside = [f for f in series.values()
              if f.start and f.start >= fs - TOL and f.end <= horizon + TOL and f.end > fs]
    discrete, ytd = {}, {}
    for f in inside:
        q = round((f.end - fs).days / 91.3)
        if 80 <= f.days <= 100 and 1 <= q <= 4:
            discrete[q] = f
        elif abs(f.start - fs) <= TOL and 100 < f.days < 350 and 1 <= q <= 3:
            ytd[q] = f
    out = {q: (f.val, [f], False) for q, f in discrete.items()}

    def cum(q):
        if q == 0:
            return 0.0, []
        if q in ytd:
            return ytd[q].val, [ytd[q]]
        if all(i in out for i in range(1, q + 1)):
            return sum(out[i][0] for i in range(1, q + 1)), sum((out[i][1] for i in range(1, q + 1)), [])
        return None, []

    if additive:
        for q in (1, 2, 3):
            if q not in out and q in ytd:
                prev, prev_src = cum(q - 1)
                if prev is not None:
                    out[q] = (ytd[q].val - prev, [ytd[q], *prev_src], True)
        if 4 not in out and annual is not None:
            c3, src = cum(3)
            if c3 is not None:
                out[4] = (annual.val - c3, [annual, *src], True)
    return out


def _find_annual(series: dict, fs: date, fe: date) -> Fact | None:
    for (s, e), f in series.items():
        if abs(s - fs) <= TOL and abs(e - fe) <= TOL and 350 <= f.days <= 380:
            return f
    return None


def _find_instant(series: dict, end: date) -> Fact | None:
    best = None
    for e, f in series.items():
        if abs(e - end) <= TOL and (best is None or abs(e - end) < abs(best.end - end)):
            best = f
    return best


def _prov(item: str, facts_used: list[Fact], derived: bool) -> dict:
    lead = facts_used[0]
    return {"tag": lead.tag, "accn": lead.accn, "form": lead.form, "filed": max(f.filed for f in facts_used),
            "first_filed": max(f.first_filed or f.filed for f in facts_used),
            "derived": derived, "accns": sorted({f.accn for f in facts_used})}


def build(company_facts: dict) -> dict:
    """Return {'annual': DataFrame, 'quarterly': DataFrame, 'provenance': dict, 'currency': str}."""
    facts = company_facts["facts"]
    fy_map = build_fy_map(facts)

    flow = {item: select_series(facts, item, spec, instant=False) for item, spec in FLOW.items()}
    inst = {item: select_series(facts, item, spec, instant=True) for item, spec in INSTANT.items()}
    currency = flow["revenue"][1] or flow["net_income"][1] or "USD"

    fys = fiscal_years([flow[k][0] for k in ("revenue", "net_income", "cfo")], fy_map)
    if not fys:
        raise ValueError("No annual periods found in company facts")
    # Open (in-progress) fiscal year after the last completed one
    last_end = fys[-1][1]
    open_fy = (last_end + timedelta(days=1), None, fys[-1][2] + 1)

    annual_rows, quarter_rows, prov = [], [], {}
    for fs, fe, fy in fys + [open_fy]:
        label = f"FY{fy}"
        quarter_ends: dict[int, date] = {}
        qvals: dict[int, dict] = {}
        arow = {"period": label, "fy": fy, "start": fs, "end": fe}
        for item, (series, unit) in flow.items():
            annual = _find_annual(series, fs, fe) if fe else None
            if annual is not None:
                arow[item] = annual.val
                prov[f"{item}|{label}"] = _prov(item, [annual], False)
            additive = item not in SHARE_COUNT
            for q, (val, used, derived) in _quarterize(series, fs, fe, annual, additive).items():
                qvals.setdefault(q, {})[item] = val
                prov[f"{item}|{label}Q{q}"] = _prov(item, used, derived)
                if not derived or q == 4:
                    quarter_ends.setdefault(q, fe if q == 4 else used[0].end)
        for q in qvals:
            if q not in quarter_ends:
                quarter_ends[q] = fe if q == 4 else fs + timedelta(days=round(91.3 * q) - 1)
        if fe:
            for item, (series, unit) in inst.items():
                f = _find_instant(series, fe)
                if f is not None:
                    arow[item] = f.val
                    prov[f"{item}|{label}"] = _prov(item, [f], False)
            annual_rows.append(arow)
        for q in sorted(qvals):
            qrow = {"period": f"{label}Q{q}", "fy": fy, "q": q, "end": quarter_ends[q], **qvals[q]}
            for item, (series, unit) in inst.items():
                f = _find_instant(series, quarter_ends[q])
                if f is not None:
                    qrow[item] = f.val
                    prov[f"{item}|{label}Q{q}"] = _prov(item, [f], False)
            quarter_rows.append(qrow)

    annual = derive(pd.DataFrame(annual_rows).set_index("period"), periods_per_year=1)
    qcols = ["period", "fy", "q", "end"]
    quarterly = derive(pd.DataFrame(quarter_rows, columns=None if quarter_rows else qcols).set_index("period"),
                       periods_per_year=4)
    return {"annual": annual, "quarterly": quarterly, "provenance": prov, "currency": currency}


def derive(df: pd.DataFrame, periods_per_year: int) -> pd.DataFrame:
    """Fill gaps and add standard derived metrics."""
    df = df.copy()
    for col in set(FLOW) | set(INSTANT):
        if col not in df:
            df[col] = np.nan

    df["gross_profit"] = df["gross_profit"].fillna(df["revenue"] - df["cost_of_revenue"])
    df["sga"] = df["sga"].fillna(df["selling_marketing"] + df["g_and_a"])
    df["d_and_a"] = df["d_and_a"].fillna(df["depreciation"] + df["amortization"].fillna(0))
    df["ebitda"] = df["operating_income"] + df["d_and_a"]
    df["fcf"] = df["cfo"] - df["capex"]
    lt = df["debt_lt_total"].fillna(df["debt_noncurrent"] + df["debt_current"].fillna(0))
    lt = lt.fillna(df["debt_noncurrent"])
    df["total_debt"] = lt.fillna(0) + df["short_borrowings"].fillna(0)
    df.loc[lt.isna() & df["short_borrowings"].isna(), "total_debt"] = np.nan
    df["net_debt"] = df["total_debt"] - df["cash"].fillna(0) - df["st_investments"].fillna(0)

    for name, num in [("gross_margin", "gross_profit"), ("operating_margin", "operating_income"),
                      ("ebitda_margin", "ebitda"), ("net_margin", "net_income"), ("fcf_margin", "fcf"),
                      ("rnd_pct", "rnd"), ("sga_pct", "sga"), ("capex_pct", "capex")]:
        df[name] = df[num] / df["revenue"]
    df["tax_rate"] = df["income_tax"] / df["pretax_income"]

    lag = periods_per_year
    for col in ("revenue", "operating_income", "ebitda", "net_income", "eps_diluted", "fcf"):
        prev = df[col].shift(lag)
        df[f"{col}_yoy"] = np.where(prev > 0, df[col] / prev - 1, np.nan)

    if periods_per_year == 1:
        avg_equity = (df["total_equity"] + df["total_equity"].shift(1)) / 2
        avg_assets = (df["total_assets"] + df["total_assets"].shift(1)) / 2
        df["roe"] = df["net_income"] / avg_equity
        df["roa"] = df["net_income"] / avg_assets
        nopat = df["operating_income"] * (1 - df["tax_rate"].clip(0, 0.5).fillna(0.21))
        invested = df["total_debt"].fillna(0) + df["total_equity"] - df["cash"].fillna(0)
        df["roic"] = nopat / invested.where(invested > 0)
    return df


def provenance_frame(prov: dict, cik: int) -> pd.DataFrame:
    rows = []
    for key, p in prov.items():
        item, period = key.split("|")
        acc = p["accn"]
        rows.append({"item": item, "period": period, **{k: v for k, v in p.items() if k != "accns"},
                     "sources": ";".join(p["accns"]),
                     "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"})
    return pd.DataFrame(rows)


__all__ = ["build", "derive", "provenance_frame", "Fact", "asdict"]
