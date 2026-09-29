"""`erb lint TICKER`: style and sourcing checks on coverage/<TICKER>/sections/*.md.

Errors (must fix before the draft goes to Ethan):
  em-dash          em dashes anywhere in prose
  unsourced        a sentence with a figure but no [Sn] or [M] tag
  unknown-source   [Sn] tag with no entry in sources.md
  pt-mismatch      a price target / rating in prose that differs from model.json
  first-person     "I"/"my"/"me" (reports speak as the team / the Fund)
Warnings:
  ai-ism           words from the banned list (guides/style_guide.md)
  number-style     15% (use 15.0%), -5.0% (use (5.0%)), Q3 2025 (use 3Q'25), FY2025 (use FY'25),
                   "billion"/"million" (use bn/mn)
  verify           open [VERIFY: ...] items
  placeholder      [SAMPLE ...] filler or "[Pun Heading" scaffold text still present
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import fmt
from .config import coverage_dir

AI_ISMS = [
    "delve", "delves", "delving", "tapestry", "landscape", "navigate", "navigating", "pivotal", "seamless",
    "seamlessly", "underscores", "underscore", "a testament to", "it's worth noting", "it is worth noting",
    "in today's", "robust", "game-changer", "game changer", "unlock the potential", "ever-evolving",
    "multifaceted", "holistic", "synergy", "leverages", "paradigm", "cutting-edge",
]
FIGURE = re.compile(r"(\$\s?\d|\d[\d,]*\.?\d*\s?(%|x\b|bps|bn|mn|tn|k\b)|\b\d{1,3}(,\d{3})+\b|\b\d+\.\d+\b)")
TAG = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*|M)\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(\"'])")


@dataclass
class Issue:
    level: str
    code: str
    file: str
    line: int
    msg: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.code:14} {self.file}:{self.line}  {self.msg}"


def _prose_lines(text: str):
    """Yield (line_no, line) for prose, skipping front matter, comments, tokens and tables."""
    lines = text.splitlines()
    in_front = lines[:1] == ["---"]
    in_comment = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if in_front:
            if i > 1 and s == "---":
                in_front = False
            continue
        if "<!--" in s and "-->" not in s:
            in_comment = True
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        s = re.sub(r"<!--.*?-->", "", s)
        if not s or s.startswith("|") or re.fullmatch(r"\{\{\s*\w+\s*\}\}", s) or s.startswith("!["):
            continue
        if s.lower().startswith("source:"):
            continue
        yield i, s


def _sources(cdir: Path) -> set[str]:
    path = cdir / "sources.md"
    if not path.exists():
        return set()
    return set(re.findall(r"^\s*-?\s*\[(S\d+)\]", path.read_text(), flags=re.M))


def _model_prices(cdir: Path) -> tuple[dict, str | None]:
    path = cdir / "model.json"
    if not path.exists():
        return {}, None
    m = json.loads(path.read_text())
    cur = m["cover"]["currency"] or "USD"
    pts = {s: m["scenarios"][s]["price_target"] for s in ("bear", "base", "bull")}
    # every per-share value the model publishes may be quoted (scenario PTs and each method)
    for s in ("bear", "base", "bull"):
        for k, v in m["scenarios"][s].get("methods", {}).items():
            pts[f"{s}_{k}"] = v
    pts["_currency"] = cur
    return pts, m["rating"]["rating"]


def lint(ticker: str) -> list[Issue]:
    cdir = coverage_dir(ticker)
    sdir = cdir / "sections"
    issues: list[Issue] = []
    known = _sources(cdir)
    pts, rating = _model_prices(cdir)
    allowed_prices = set()
    if pts:
        cur = pts.pop("_currency")
        for v in pts.values():
            allowed_prices |= {fmt.price(v, cur), fmt.price(v, cur).replace(".00", ""),
                               f"${v:,.1f}", f"${v:,.0f}", f"${round(v):,}"}

    for path in sorted(sdir.glob("*.md")):
        name = path.name
        text = path.read_text()
        for ln, s in _prose_lines(text):
            def add(level, code, msg):
                issues.append(Issue(level, code, name, ln, msg))

            if "—" in s:
                add("error", "em-dash", "em dash; use a comma, colon or parentheses")
            if re.search(r"[A-Za-z]\s?–\s?[A-Za-z]", s):
                add("warn", "number-style", "en dash between words; en dashes are for numeric ranges")
            if not s.startswith("#") and re.search(r"\b(I|I'm|I've|my|me|mine)\b",
                                                   re.sub(r"\[.*?\]|Exhibit [IVX]+", "", s)):
                add("error", "first-person", "first person singular; write as the team / the Fund")
            low = s.lower()
            for w in AI_ISMS:
                if re.search(rf"\b{re.escape(w)}\b", low):
                    add("warn", "ai-ism", f"'{w}'")
            if "[SAMPLE" in s or "[Pun Heading" in s or re.search(r"\[(Segment|Catalyst|Risk|Peer) (A|B|One|Two|Three)", s):
                add("warn", "placeholder", "scaffold or sample text still present")
            for v in re.findall(r"\[VERIFY:[^\]]*\]", s):
                add("warn", "verify", v)
            for tag in re.findall(r"\[(S\d+(?:\s*,\s*S\d+)*)\]", s):
                for t in re.split(r"\s*,\s*", tag):
                    if t not in known:
                        add("error", "unknown-source", f"[{t}] not in sources.md")
            # number style
            clean = TAG.sub("", s)
            if re.search(r"(?<![\d.])\d+%", clean):
                add("warn", "number-style", "percent without a decimal (15% -> 15.0%)")
            if re.search(r"(?<![\w(])-\d[\d.,]*%", clean):
                add("warn", "number-style", "negative percent; use parentheses (5.0%)")
            if re.search(r"\bQ[1-4]\s?'?\d{2,4}\b|\b[1-4]Q\s?20\d{2}\b", clean):
                add("warn", "number-style", "quarter format; use 3Q'25")
            if re.search(r"\b(FY|CY)\s?20\d{2}\b", clean):
                add("warn", "number-style", "year format; use FY'25 / CY'25")
            if re.search(r"\b\d[\d.,]*\s?(billion|million|trillion)\b", clean, re.I):
                add("warn", "number-style", "use bn / mn / tn")
            # sourcing: every sentence with a figure needs a tag
            if not s.startswith("#"):
                body = s[2:] if s.startswith(("- ", "* ")) else s
                for sent in SENTENCE_END.split(body):
                    no_verify = re.sub(r"\[VERIFY:[^\]]*\]", "", sent)
                    if FIGURE.search(TAG.sub("", no_verify)) and not TAG.search(sent) and "[VERIFY" not in sent:
                        add("error", "unsourced", f"figure without [Sn]/[M]: \"{sent[:90]}\"")
            # price targets / rating must match the model
            if allowed_prices:
                # only amounts stated as *our* target, e.g. "price target of $951.30", "bull case of $1,324.91";
                # analyst actions ("lifted its price target from $640 to $796") are other people's targets
                ours = []
                for sent in SENTENCE_END.split(s):
                    if re.search(r"\b(lifted|raised|cut|lowered|reiterat|maintain|Street|consensus|analyst)", sent, re.I):
                        continue
                    ours += re.findall(r"(?:price target|\bPT|(?:bear|base|bull)[ -]cases?)(?:\s+(?:of|at|is|to))?\s+(\$[\d,]+(?:\.\d+)?)", sent, re.I)
                for p in ours:
                    if p not in allowed_prices and p.rstrip("0").rstrip(".") not in {a.rstrip("0").rstrip(".") for a in allowed_prices}:
                        add("error", "pt-mismatch", f"{p} near 'price target' is not a model.json target")
            if rating:
                for r in re.findall(r"\b(Outperform|Neutral|Underperform)\b", s):
                    if r != rating and "rating" in low:
                        add("error", "pt-mismatch", f"rating '{r}' but model says {rating}")
    return issues


def report(ticker: str, log=print) -> int:
    issues = lint(ticker)
    errors = [i for i in issues if i.level == "error"]
    for i in sorted(issues, key=lambda x: (x.level != "error", x.file, x.line)):
        log(str(i))
    counts = {}
    for i in issues:
        counts[i.code] = counts.get(i.code, 0) + 1
    log(f"\n{len(errors)} errors, {len(issues) - len(errors)} warnings  " +
        ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if errors else 0
