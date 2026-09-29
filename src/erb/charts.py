"""`erb charts TICKER`: standard report exhibits as 300-dpi PNGs in coverage/<TICKER>/charts/.

Design rules (dataviz skill): one y-axis per chart (growth rates are labels, not a
second axis), thin marks, 2px lines, hairline solid gridlines, text in ink tones
(never the series colour), a legend for 2+ series plus selective direct labels,
fixed categorical order from assets/brand.yaml, and at most 3 hues where every
pair shows at once.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import fmt  # noqa: E402
from .config import ASSETS_DIR, coverage_dir  # noqa: E402

BRAND = yaml.safe_load((ASSETS_DIR / "brand.yaml").read_text())
C = BRAND["colors"]
CAT = C["categorical"]
FULL_W, HALF_W = 7.0, 3.4  # inches


def _style() -> None:
    plt.rcParams.update({
        "font.family": BRAND["fonts"]["chart"], "font.size": 7.5,
        "text.color": C["ink"], "axes.labelcolor": C["text_secondary"],
        "xtick.color": C["text_secondary"], "ytick.color": C["text_secondary"],
        "xtick.labelsize": 7, "ytick.labelsize": 7,
        "axes.edgecolor": C["grid"], "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": C["grid"], "grid.linewidth": 0.6,
        "grid.linestyle": "-", "axes.axisbelow": True,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "legend.frameon": False, "legend.fontsize": 7,
        "figure.facecolor": C["surface"], "axes.facecolor": C["surface"],
        "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.04,
        "lines.linewidth": 1.4, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    })


def _title(ax, text: str) -> None:
    ax.set_title(text, loc="left", fontsize=8.5, fontweight="bold", color=C["ink"], pad=6)


def _money_axis(ax, cur: str = "USD", per_share: bool = False) -> None:
    if per_share:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt.price(v, cur).replace(".00", "")))
    else:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt.money(v, cur, 0)))


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- charts

def price_targets(model: dict, prices: pd.DataFrame, out: Path) -> Path:
    """One year of price history, fanning to bear/base/bull targets at the target date."""
    as_of = pd.Timestamp(model["assumptions"]["as_of"])
    cur = model["cover"]["currency"] or "USD"
    hist = prices["close"][prices.index >= as_of - pd.Timedelta(days=365)]
    target = pd.Timestamp(model["scenarios"]["base"]["target_date"])
    fig, ax = plt.subplots(figsize=(FULL_W, 2.5))
    ax.plot(hist.index, hist.values, color=C["scenario"]["price"], linewidth=1.4, label="Last Price")
    last = float(hist.iloc[-1])
    for s, label in (("bear", "Bear Case"), ("base", "Base Case"), ("bull", "Bull Case")):
        pt = model["scenarios"][s]["price_target"]
        col = C["scenario"][s]
        ax.plot([hist.index[-1], target], [last, pt], color=col, linewidth=1.6, label=label)
        ax.scatter([target], [pt], s=22, color=col, edgecolor=C["surface"], linewidth=1.2, zorder=3)
        ax.annotate(fmt.price(pt, cur), (target, pt), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=7, color=C["ink"])
    ax.axvline(hist.index[-1], color=C["grid"], linewidth=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    _money_axis(ax, cur, per_share=True)
    ax.set_xlim(hist.index[0], target + pd.Timedelta(days=75))
    ax.legend(loc="upper left", ncol=4)
    _title(ax, f"{model['ticker']} Price Target Scenarios")
    return _save(fig, out)


def multiple_bands(mh: pd.DataFrame, col: str, label: str, ticker: str, out: Path) -> Path | None:
    """1/2/3-year panels of an LTM multiple with its median (point-in-time, from filings)."""
    s = mh[col].dropna()
    if s.empty:
        return None
    s.index = pd.to_datetime(s.index)
    end = s.index[-1]
    fig, axes = plt.subplots(1, 3, figsize=(FULL_W, 1.9), sharey=False)
    for ax, years in zip(axes, (1, 2, 3)):
        w = s[s.index >= end - pd.DateOffset(years=years)]
        med = float(w.median())
        ax.plot(w.index, w.values, color=CAT[0], linewidth=1.3, label=label)
        ax.axhline(med, color=C["text_muted"], linewidth=1.0, label="Median")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}x"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4 * years))
        ax.set_title(f"{['One', 'Two', 'Three'][years - 1]} Year · median {med:.1f}x", loc="left",
                     fontsize=7, color=C["text_secondary"], pad=4)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=6.5, bbox_to_anchor=(0.5, -0.03))
    fig.suptitle(f"{ticker} {label} vs. Median", x=0.01, ha="left", fontsize=8.5, fontweight="bold", color=C["ink"])
    fig.tight_layout(w_pad=1.5, rect=(0, 0.06, 1, 0.97))
    return _save(fig, out)


def segment_mix(mix: pd.DataFrame, title: str, cur: str, out: Path) -> Path | None:
    """Horizontal bars of revenue share (largest first); more than 5 members fold into Other."""
    if mix is None or mix.empty:
        return None
    mix = mix.sort_values("value", ascending=False)
    if len(mix) > 5:
        top, rest = mix.iloc[:4], mix.iloc[4:]
        mix = pd.concat([top, pd.DataFrame([{"label": "Other", "value": rest["value"].sum(), "pct": rest["pct"].sum()}])])
    mix = mix.iloc[::-1]
    fig, ax = plt.subplots(figsize=(HALF_W, 0.35 * len(mix) + 0.6))
    colors = [C["other"] if l == "Other" else CAT[0] for l in mix["label"]]
    ax.barh(mix["label"], mix["pct"], height=0.55, color=colors)
    for y, (p, v) in enumerate(zip(mix["pct"], mix["value"])):
        ax.annotate(f"{fmt.pct(p)}  ({fmt.money(v, cur)})", (p, y), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=6.8, color=C["ink"])
    ax.set_xlim(0, max(mix["pct"]) * 1.45)
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", labelsize=7, labelcolor=C["ink"])
    _title(ax, title)
    return _save(fig, out)


def financial_grid(model: dict, annual: pd.DataFrame, out: Path) -> Path:
    """Revenue, EBITDA, FCF and EPS: 3 actual + 5 projected years. Growth labelled, no second axis."""
    base = pd.DataFrame(model["projections"]["base"]).set_index("fy")
    a = annual.dropna(subset=["revenue"]).tail(3)
    lst = model["assumptions"].get("listing") or {}
    conv = float(lst.get("shares_per_unit", 1)) / float(lst.get("fx_local_per_trading", 1))
    cur_fin = model["assumptions"].get("financial_currency") or (model["cover"]["currency"] if not lst else "USD")
    panels = [("Revenue", "revenue", "revenue", False), ("EBITDA", "ebitda", "ebitda", False),
              ("FCF (A: CFO less CapEx; E: unlevered)", "fcf", "ufcf", False), ("EPS", "eps_diluted", "eps", True)]
    fig, axes = plt.subplots(2, 2, figsize=(FULL_W, 3.8))
    for ax, (name, hist_col, proj_col, per_share) in zip(axes.flat, panels):
        hv = list(a[hist_col].astype(float))
        pv = list(base[proj_col].astype(float))
        if per_share and lst:
            hv, pv = [v * conv for v in hv], [v * conv for v in pv]
        labels = [fmt.fy(int(y)) + "A" for y in a["fy"]] + [fmt.fy(int(y)) + "E" for y in base.index]
        vals = hv + pv
        x = np.arange(len(vals))
        colors = [CAT[0]] * len(hv) + [C["surface"]] * len(pv)
        bars = ax.bar(x, vals, width=0.6, color=colors, edgecolor=[CAT[0]] * len(vals), linewidth=0.9)
        for b in bars[len(hv):]:
            b.set_hatch("////")
        for i in range(1, len(vals)):
            if vals[i - 1] and vals[i - 1] > 0:
                g = vals[i] / vals[i - 1] - 1
                ax.annotate(fmt.pct(g), (x[i], max(vals[i], 0)), xytext=(0, 2), textcoords="offset points",
                            ha="center", fontsize=5.8, color=C["text_secondary"])
        ax.set_xticks(x, labels, fontsize=6)
        ax.axhline(0, color=C["text_muted"], linewidth=0.6)
        if per_share:
            _money_axis(ax, "USD" if lst else cur_fin, per_share=True)
        else:
            _money_axis(ax, cur_fin)
        _title(ax, f"{model['ticker']} {name}")
        ax.title.set_fontsize(7.5)
    handles = [plt.Rectangle((0, 0), 1, 1, color=CAT[0]),
               plt.Rectangle((0, 0), 1, 1, facecolor=C["surface"], edgecolor=CAT[0], hatch="////")]
    fig.legend(handles, ["Actual", "Estimate (base case)"], loc="lower center", ncol=2, fontsize=6.5,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(h_pad=1.2, w_pad=1.5, rect=(0, 0.04, 1, 1))
    return _save(fig, out)


def football_field(model: dict, out: Path) -> Path:
    ff = {k: v for k, v in model["football_field"].items() if v and None not in v}
    cur = model["cover"]["currency"] or "USD"
    price = model["price"]
    pt = model["scenarios"]["base"]["price_target"]
    names = list(ff)[::-1]
    fig, ax = plt.subplots(figsize=(FULL_W, 0.34 * len(names) + 0.8))
    for i, n in enumerate(names):
        lo, hi = sorted(ff[n])
        ax.barh(i, hi - lo, left=lo, height=0.5, color=CAT[0])
        ax.annotate(fmt.price(lo, cur), (lo, i), xytext=(-4, 0), textcoords="offset points", ha="right",
                    va="center", fontsize=6.5, color=C["text_secondary"])
        ax.annotate(fmt.price(hi, cur), (hi, i), xytext=(4, 0), textcoords="offset points", ha="left",
                    va="center", fontsize=6.5, color=C["text_secondary"])
    ax.set_yticks(range(len(names)), names, fontsize=7, color=C["ink"])
    left_first = price <= pt
    for x, label, col, right in ((price, "Current", C["ink"], not left_first), (pt, "Base PT", CAT[1], left_first)):
        ax.axvline(x, color=col, linewidth=1.2)
        ax.annotate(f"{label} {fmt.price(x, cur)}", (x, len(names) - 0.4), xytext=(4 if right else -4, 0),
                    textcoords="offset points", fontsize=6.5, color=C["ink"], va="bottom",
                    ha="left" if right else "right")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt.price(v, cur).replace(".00", "")))
    lo_all = min(min(v) for v in ff.values())
    hi_all = max(max(v) for v in ff.values())
    pad = (hi_all - lo_all) * 0.12
    ax.set_xlim(lo_all - pad, hi_all + pad)
    ax.set_ylim(-0.6, len(names) - 0.1)
    _title(ax, f"{model['ticker']} Valuation Football Field (per share)")
    return _save(fig, out)


# ---------------------------------------------------------------- orchestration

def render_all(ticker: str, log=print) -> dict[str, str]:
    from . import segments as seg_mod

    cdir = coverage_dir(ticker)
    fdir = cdir / "facts"
    model = json.loads((cdir / "model.json").read_text())
    prices = pd.read_csv(fdir / "prices.csv", index_col=0, parse_dates=True)
    annual = pd.read_csv(fdir / "financials_annual.csv", index_col="period")
    company = json.loads((fdir / "company.json").read_text())
    model["assumptions"]["financial_currency"] = company["financial_currency"]
    out_dir = cdir / "charts"
    _style()
    made = {}
    made["price_targets"] = price_targets(model, prices, out_dir / "price_targets.png")
    mh_path = fdir / "multiples_history.csv"
    if mh_path.exists():
        mh = pd.read_csv(mh_path, index_col="date")
        for col, label in (("ltm_pe", "LTM P/E"), ("ltm_ev_ebitda", "LTM EV/EBITDA")):
            p = multiple_bands(mh, col, label, model["ticker"], out_dir / f"band_{col}.png")
            if p:
                made[f"band_{col}"] = p
    seg_path = fdir / "segments.csv"
    if seg_path.exists() and seg_path.stat().st_size > 1:
        seg = pd.read_csv(seg_path)
        total = float(annual["revenue"].dropna().iloc[-1])
        for dim, title in (("segment", "Revenue by Segment"), ("geography", "Revenue by Geography"),
                           ("product", "Revenue by Product")):
            mix = seg_mod.latest_mix(seg, dim, total)
            if mix is not None and not mix.empty and not mix["overlap"].iloc[0]:
                fy = int(annual["fy"].dropna().iloc[-1])
                p = segment_mix(mix, f"{model['ticker']} {fmt.fy(fy)} {title}", company["financial_currency"],
                                out_dir / f"mix_{dim}.png")
                if p:
                    made[f"mix_{dim}"] = p
    made["financial_grid"] = financial_grid(model, annual, out_dir / "financial_grid.png")
    made["football_field"] = football_field(model, out_dir / "football_field.png")
    (out_dir / "index.json").write_text(json.dumps({k: str(v) for k, v in made.items()}, indent=2))
    log(f"Wrote {len(made)} charts to {out_dir}: {', '.join(made)}")
    return {k: str(v) for k, v in made.items()}
