"""Clean text sections from 10-K, 10-Q, 20-F and 8-K earnings releases."""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .edgar import Filing

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BLOCKS = ["p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]

# (name, start pattern, end pattern); headings must begin a line
SECTIONS = {
    "10-K": [
        ("business", r"item\s*1[\s.:|]*business", r"item\s*1a[\s.:|]"),
        ("risk_factors", r"item\s*1a[\s.:|]*risk\s+factors", r"item\s*(1b|1c|2)[\s.:|]"),
        ("mdna", r"item\s*7[\s.:|]*management", r"item\s*(7a|8)[\s.:|]"),
    ],
    "10-Q": [
        ("mdna", r"item\s*2[\s.:|]*management", r"item\s*(3|4)[\s.:|]"),
        ("risk_factors", r"item\s*1a[\s.:|]*risk\s+factors", r"item\s*(2|5|6)[\s.:|]"),
    ],
    "20-F": [
        ("key_information", r"item\s*3[\s.:|]*key\s+information", r"item\s*4[\s.:|]"),
        ("business", r"item\s*4[\s.:|]*information\s+on\s+the\s+company", r"item\s*(4a|5)[\s.:|]"),
        ("mdna", r"item\s*5[\s.:|]*operating\s+and\s+financial", r"item\s*6[\s.:|]"),
    ],
}
# Sections a filing may legitimately omit or merely cross-reference (e.g. "no material changes")
OPTIONAL = {("10-Q", "risk_factors")}
SECTIONS["10-K/A"] = SECTIONS["10-K"]
SECTIONS["20-F/A"] = SECTIONS["20-F"]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for el in soup.find_all(["script", "style"]):
        el.decompose()
    for el in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        el.decompose()
    for header in soup.find_all(re.compile(r"^ix:header$", re.I)):
        header.decompose()
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c not in ("$", "%", ")")]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")
    for tag in soup.find_all(BLOCKS):
        tag.append("\n")
    text = soup.get_text("")
    text = text.replace("\xa0", " ").replace("​", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if re.fullmatch(r"(\d{1,3}|table of contents|[ivx]+)", line, re.I):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_section(text: str, start: str, end: str) -> str:
    """Text from a start heading to the next end heading.

    Tables of contents repeat every heading, so each candidate span is checked:
    spans containing other "Item N." headings are TOC spans and lose to clean
    ones. Among clean spans the longest wins.
    """
    starts = list(re.finditer(rf"(?im)^[ \t]*{start}", text))
    end_re = re.compile(rf"(?im)^[ \t]*{end}")
    any_item = re.compile(r"(?im)^[ \t]*item\s*\d+[a-d]?[\s.:|]")
    clean, dirty = [], []
    for i, m in enumerate(starts):
        e = end_re.search(text, m.end())
        stop = e.start() if e else len(text)
        if i + 1 < len(starts):
            stop = min(stop, starts[i + 1].start())
        chunk = text[m.start(): stop].strip()
        (dirty if any_item.search(chunk, len(m.group(0))) else clean).append(chunk)
    pool = clean or dirty
    return max(pool, key=len) if pool else ""


def sections(filing: Filing) -> dict[str, str]:
    text = html_to_text(filing.fetch())
    specs = SECTIONS.get(filing.form, [])
    out = {name: extract_section(text, s, e) for name, s, e in specs}
    out = {k: v for k, v in out.items() if len(v) > 500}
    out["full_text"] = text
    return out


def earnings_release(filing: Filing) -> tuple[str, str] | None:
    """Exhibit 99.1 text from an 8-K (Item 2.02), with its URL."""
    names = [f["name"] for f in filing.files() if f["name"].lower().endswith((".htm", ".html"))]
    pick = sorted(n for n in names if re.search(r"ex-?99|ex991|exhibit99|dex99|press.?release|earnings", n, re.I))
    if not pick:
        sizes = {f["name"]: int(f.get("size") or 0) for f in filing.files()}
        others = [n for n in names if n != filing.primary_document and "index" not in n
                  and not re.fullmatch(r"R\d+\.htm", n)]
        pick = sorted(others, key=lambda n: -sizes.get(n, 0))
    if not pick:
        return None
    name = pick[0]
    return html_to_text(filing.fetch(name)), filing.file_url(name)
