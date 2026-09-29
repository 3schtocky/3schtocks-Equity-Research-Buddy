"""Segment, product and geographic breakdowns from a filing's XBRL instance.

EDGAR's companyfacts API drops dimensional facts, so segment revenue has to be
read from the filing itself (the SEC-generated `*_htm.xml` instance).
"""

from __future__ import annotations

import re

import pandas as pd
from lxml import etree

from .edgar import Filing

AXES = {
    "StatementBusinessSegmentsAxis": "segment",
    "SegmentsAxis": "segment",
    "ProductOrServiceAxis": "product",
    "ProductsAndServicesAxis": "product",
    "StatementGeographicalAxis": "geography",
    "GeographicalAreasAxis": "geography",
}
CONCEPTS = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "revenue",
    "RevenuesNetOfInterestExpense": "revenue",
    "Revenue": "revenue",
    "RevenueFromContractsWithCustomers": "revenue",
    "OperatingIncomeLoss": "operating_income",
    "ProfitLossFromOperatingActivities": "operating_income",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _humanize(qname: str) -> str:
    name = qname.split(":")[-1].removesuffix("Member")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)


def _labels(filing: Filing, names: list[str]) -> dict[str, str]:
    lab = next((n for n in names if n.endswith("_lab.xml")), None)
    if not lab:
        return {}
    root = etree.fromstring(filing.fetch(lab).encode())
    xl = "{http://www.w3.org/1999/xlink}"
    locs, texts, out = {}, {}, {}
    for el in root.iter():
        name = _local(el.tag) if isinstance(el.tag, str) else ""
        if name == "loc":
            locs[el.get(xl + "label")] = el.get(xl + "href", "").split("#")[-1]
        elif name == "label" and (el.get(xl + "role") or "").endswith("/label"):
            texts[el.get(xl + "label")] = (el.text or "").strip()
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el.tag) == "labelArc":
            elem_id = locs.get(el.get(xl + "from"))
            text = texts.get(el.get(xl + "to"))
            if elem_id and text:
                out[elem_id.replace("_", ":", 1)] = re.sub(r"\s*\[(member|domain)\]$", "", text, flags=re.I)
    return out


def _instance_name(names: list[str]) -> str | None:
    inst = [n for n in names if n.endswith("_htm.xml")]
    if inst:
        return inst[0]
    skip = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "FilingSummary.xml")
    xmls = [n for n in names if n.endswith(".xml") and not n.endswith(skip)]
    return xmls[0] if xmls else None


def extract(filing: Filing) -> pd.DataFrame:
    """Long table: dimension, member, label, concept, start, end, value, accession."""
    names = [f["name"] for f in filing.files()]
    inst_name = _instance_name(names)
    if not inst_name:
        return pd.DataFrame()
    root = etree.fromstring(filing.fetch(inst_name).encode())

    contexts = {}
    for ctx in root.iter():
        if not isinstance(ctx.tag, str) or _local(ctx.tag) != "context":
            continue
        members = [m for m in ctx.iter() if isinstance(m.tag, str) and _local(m.tag) in ("explicitMember", "typedMember")]
        if len(members) != 1 or _local(members[0].tag) != "explicitMember":
            continue
        axis = members[0].get("dimension", "").split(":")[-1]
        if axis not in AXES:
            continue
        dates = {_local(d.tag): d.text for d in ctx.iter() if isinstance(d.tag, str) and _local(d.tag) in ("startDate", "endDate")}
        if "startDate" not in dates:
            continue
        contexts[ctx.get("id")] = (AXES[axis], members[0].text.strip(), dates["startDate"], dates["endDate"])

    labels = _labels(filing, names)
    rows, seen = [], set()
    for el in root:
        if not isinstance(el.tag, str):
            continue
        concept = CONCEPTS.get(_local(el.tag))
        ctx = contexts.get(el.get("contextRef"))
        if not concept or not ctx or el.text is None:
            continue
        dim, member, start, end = ctx
        key = (dim, member, concept, start, end)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "dimension": dim, "member": member, "label": labels.get(member) or _humanize(member),
            "concept": concept, "tag": _local(el.tag), "start": start, "end": end, "value": float(el.text),
            "form": filing.form, "accession": filing.accession, "url": filing.index_url,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["days"] = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days + 1
    return df


def latest_mix(seg: pd.DataFrame, dimension: str = "segment", total_revenue: float | None = None,
               concept: str = "revenue") -> pd.DataFrame:
    """Members for the most recent annual period with % of consolidated revenue.

    Members can overlap (a region and a country inside it, or a sub-line inside a
    line), so percentages are taken against consolidated revenue, not the member sum.
    `overlap` is True when the members add up to more than the total.
    """
    if seg.empty:
        return seg
    df = seg[(seg["dimension"] == dimension) & (seg["concept"] == concept) & seg["days"].between(350, 380)]
    if df.empty:
        return df
    df = df[df["end"] == df["end"].max()].copy()
    total = total_revenue or df["value"].sum()
    df["pct"] = df["value"] / total
    df["overlap"] = df["value"].sum() > total * 1.01
    return df.sort_values("value", ascending=False)[["label", "value", "pct", "end", "tag", "overlap"]]
