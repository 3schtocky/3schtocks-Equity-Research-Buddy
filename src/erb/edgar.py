"""SEC EDGAR client: ticker lookup, submissions, XBRL company facts, filing documents.

All requests carry the SEC-required User-Agent, are throttled under the SEC's
10 requests/second limit and are cached on disk. Archive documents never change,
so they are cached forever; API responses are refreshed daily.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import CACHE_DIR, SEC_USER_AGENT

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{name}"

DAY = 86_400
_session = requests.Session()
_session.headers.update({"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
_last_request = 0.0


def _get(url: str, ttl: float | None, binary: bool = False, refresh: bool = False):
    """GET with disk cache. ttl=None caches forever."""
    global _last_request
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    fresh = path.exists() and (ttl is None or time.time() - path.stat().st_mtime < ttl)
    if fresh and not refresh:
        data = path.read_bytes()
    else:
        wait = 0.12 - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            _last_request = time.time()
            resp = _session.get(url, timeout=60)
            if resp.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            break
        else:
            resp.raise_for_status()
        data = resp.content
        path.write_bytes(data)
    return data if binary else json.loads(data)


def _get_text(url: str) -> str:
    return _get(url, ttl=None, binary=True).decode("utf-8", errors="replace")


@dataclass
class Company:
    cik: int
    ticker: str
    name: str
    exchange: str | None


def lookup(ticker: str) -> Company:
    """Resolve a ticker (e.g. META, BRK-B, BRK.B) to its CIK."""
    data = _get(TICKERS_URL, ttl=7 * DAY)
    wanted = {ticker.upper(), ticker.upper().replace(".", "-"), ticker.upper().replace("-", ".")}
    for cik, name, tick, exch in data["data"]:
        if tick.upper() in wanted:
            return Company(cik=cik, ticker=tick.upper(), name=name, exchange=exch)
    raise KeyError(f"Ticker {ticker} not found in SEC company_tickers_exchange.json")


def all_tickers() -> list[Company]:
    data = _get(TICKERS_URL, ttl=7 * DAY)
    return [Company(cik=c, ticker=t, name=n, exchange=e) for c, n, t, e in data["data"]]


def submissions(cik: int, refresh: bool = False) -> dict:
    return _get(SUBMISSIONS_URL.format(cik=cik), ttl=DAY, refresh=refresh)


def company_facts(cik: int, refresh: bool = False) -> dict:
    return _get(FACTS_URL.format(cik=cik), ttl=DAY, refresh=refresh)


def frames(tag: str, unit: str, period: str, taxonomy: str = "us-gaap") -> dict:
    """One concept across all filers for a period, e.g. frames('Revenues', 'USD', 'CY2024')."""
    return _get(FRAMES_URL.format(taxonomy=taxonomy, tag=tag, unit=unit, period=period), ttl=DAY)


@dataclass
class Filing:
    form: str
    accession: str
    filing_date: str
    report_date: str
    primary_document: str
    items: str
    cik: int

    @property
    def folder_url(self) -> str:
        return ARCHIVE_URL.format(cik=self.cik, accn_nodash=self.accession.replace("-", ""), name="")

    @property
    def url(self) -> str:
        return self.folder_url + self.primary_document

    @property
    def index_url(self) -> str:
        return self.folder_url + f"{self.accession}-index.htm"

    def file_url(self, name: str) -> str:
        return self.folder_url + name

    def files(self) -> list[dict]:
        idx = _get(self.folder_url + "index.json", ttl=None)
        return idx["directory"]["item"]

    def fetch(self, name: str | None = None) -> str:
        return _get_text(self.file_url(name or self.primary_document))


def filings(cik: int, forms: tuple[str, ...], refresh: bool = False) -> list[Filing]:
    """Recent filings of the given forms, newest first."""
    sub = submissions(cik, refresh=refresh)
    recent = sub["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form in forms:
            out.append(
                Filing(
                    form=form,
                    accession=recent["accessionNumber"][i],
                    filing_date=recent["filingDate"][i],
                    report_date=recent["reportDate"][i],
                    primary_document=recent["primaryDocument"][i],
                    items=recent.get("items", [""] * len(recent["form"]))[i],
                    cik=cik,
                )
            )
    return out


def latest(cik: int, forms: tuple[str, ...], items_contains: str | None = None) -> Filing | None:
    for f in filings(cik, forms):
        if items_contains is None or items_contains in (f.items or ""):
            return f
    return None


def accession_url(cik: int, accession: str) -> str:
    return ARCHIVE_URL.format(cik=cik, accn_nodash=accession.replace("-", ""), name=f"{accession}-index.htm")


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
