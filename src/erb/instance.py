"""Read non-dimensional facts straight from a filing's XBRL instance.

EDGAR's companyfacts API can lag new filings by weeks (seen with 20-F filers).
Merging the latest 10-K/20-F/10-Q instances into companyfacts guarantees the
newest reported period is always present.
"""

from __future__ import annotations

from lxml import etree

from .edgar import Filing
from .segments import _instance_name, _local


def _units(root) -> dict[str, str]:
    out = {}
    for u in root:
        if not isinstance(u.tag, str) or _local(u.tag) != "unit":
            continue
        measures = [m.text.split(":")[-1] for m in u.iter() if isinstance(m.tag, str) and _local(m.tag) == "measure"]
        divide = any(isinstance(d.tag, str) and _local(d.tag) == "divide" for d in u.iter())
        out[u.get("id")] = "/".join(measures) if divide and len(measures) == 2 else (measures[0] if measures else "")
    return out


def _contexts(root) -> dict[str, dict]:
    out = {}
    for ctx in root:
        if not isinstance(ctx.tag, str) or _local(ctx.tag) != "context":
            continue
        if any(isinstance(m.tag, str) and _local(m.tag) in ("explicitMember", "typedMember") for m in ctx.iter()):
            continue  # dimensional; companyfacts only carries entity-wide facts
        dates = {_local(d.tag): (d.text or "").strip() for d in ctx.iter()
                 if isinstance(d.tag, str) and _local(d.tag) in ("startDate", "endDate", "instant")}
        if "instant" in dates:
            out[ctx.get("id")] = {"end": dates["instant"]}
        elif "endDate" in dates:
            out[ctx.get("id")] = {"start": dates["startDate"], "end": dates["endDate"]}
    return out


def facts(filing: Filing) -> dict:
    """Companyfacts-shaped dict {taxonomy: {tag: {"units": {unit: [rows]}}}} for one filing."""
    names = [f["name"] for f in filing.files()]
    inst = _instance_name(names)
    if not inst:
        return {}
    root = etree.fromstring(filing.fetch(inst).encode())
    units, contexts = _units(root), _contexts(root)
    meta = {}
    for el in root:
        if isinstance(el.tag, str) and el.prefix == "dei" and el.text:
            meta[_local(el.tag)] = el.text.strip()
    fy = int(meta["DocumentFiscalYearFocus"]) if meta.get("DocumentFiscalYearFocus", "").isdigit() else None
    fp = meta.get("DocumentFiscalPeriodFocus")
    out: dict = {}
    for el in root:
        if not isinstance(el.tag, str) or el.prefix not in ("us-gaap", "ifrs-full") or el.text is None:
            continue
        ctx = contexts.get(el.get("contextRef"))
        unit = units.get(el.get("unitRef"))
        if not ctx or not unit:
            continue
        try:
            val = float(el.text.strip())
        except ValueError:
            continue
        row = {**ctx, "val": val, "accn": filing.accession, "fy": fy, "fp": fp,
               "form": filing.form, "filed": filing.filing_date}
        out.setdefault(el.prefix, {}).setdefault(_local(el.tag), {"units": {}})["units"].setdefault(unit, []).append(row)
    return out


def merge(company_facts: dict, extra: dict) -> dict:
    """Add instance facts to companyfacts where that accession isn't already present."""
    target = company_facts["facts"]
    for taxonomy, tags in extra.items():
        for tag, node in tags.items():
            dest = target.setdefault(taxonomy, {}).setdefault(tag, {"units": {}})
            for unit, rows in node["units"].items():
                have = dest["units"].setdefault(unit, [])
                seen = {(r.get("start"), r["end"], r["accn"]) for r in have}
                have.extend(r for r in rows if (r.get("start"), r["end"], r["accn"]) not in seen)
    return company_facts
