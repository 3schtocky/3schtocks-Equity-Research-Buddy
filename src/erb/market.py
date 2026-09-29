"""Market data from Yahoo Finance (via yfinance): quote snapshot, prices, consensus, peers.

Prices are "as of the previous close", matching the convention on report covers.
Dividend yield is computed as annual dividend rate / price to avoid Yahoo's
inconsistent units.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf


def _yf_symbol(ticker: str) -> str:
    """US share classes use a dash on Yahoo (BRK.B -> BRK-B); exchange suffixes keep the dot (SMSN.IL)."""
    t = ticker.upper()
    base, _, suffix = t.rpartition(".")
    return f"{base}-{suffix}" if base and len(suffix) == 1 else t


def history(ticker: str, period: str = "5y") -> pd.DataFrame:
    df = yf.Ticker(_yf_symbol(ticker)).history(period=period, auto_adjust=False)
    if df.empty:
        raise ValueError(f"No price history for {ticker}")
    df.index = df.index.tz_localize(None).normalize()
    return df[["Close", "Adj Close", "Volume"]].rename(columns=str.lower).rename(columns={"adj close": "adj_close"})


def _ret(prices: pd.Series, since: pd.Timestamp) -> float | None:
    base = prices[prices.index <= since]
    return None if base.empty else float(prices.iloc[-1] / base.iloc[-1] - 1)


def snapshot(ticker: str, prices: pd.DataFrame | None = None) -> dict:
    t = yf.Ticker(_yf_symbol(ticker))
    info = t.info or {}
    prices = prices if prices is not None else history(ticker, "2y")
    close = prices["close"]
    adj = prices["adj_close"]
    last = close.index[-1]
    price = float(close.iloc[-1])
    year_ago = close[close.index >= last - pd.Timedelta(days=365)]
    div_rate = info.get("dividendRate") or 0.0

    def ts(key):
        v = info.get(key)
        return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat() if v else None

    try:
        cal = t.calendar or {}
        next_earnings = cal.get("Earnings Date", [None])[0]
    except Exception:
        next_earnings = None

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName") or info.get("shortName"),
        "as_of": last.date().isoformat(),
        "price": price,
        "currency": info.get("currency"),
        "financial_currency": info.get("financialCurrency"),
        "exchange": info.get("fullExchangeName") or info.get("exchange"),
        "quote_type": info.get("quoteType"),
        "week52_low": float(year_ago.min()),
        "week52_high": float(year_ago.max()),
        "ytd_return": _ret(adj, pd.Timestamp(last.year - 1, 12, 31)),
        "one_year_return": _ret(adj, last - pd.Timedelta(days=365)),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "total_debt": info.get("totalDebt"),
        "total_cash": info.get("totalCash"),
        "ebitda_ttm": info.get("ebitda"),
        "dividend_rate": div_rate,
        "dividend_yield": div_rate / price if price else None,
        "beta": info.get("beta"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": info.get("fullTimeEmployees"),
        "hq": ", ".join(x for x in (info.get("city"), info.get("state"), info.get("country")) if x),
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "last_fiscal_year_end": ts("lastFiscalYearEnd"),
        "next_fiscal_year_end": ts("nextFiscalYearEnd"),
        "most_recent_quarter": ts("mostRecentQuarter"),
        "next_earnings_date": str(next_earnings) if next_earnings else None,
        "target_mean": info.get("targetMeanPrice"),
        "target_median": info.get("targetMedianPrice"),
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
        "source": f"https://finance.yahoo.com/quote/{_yf_symbol(ticker)}",
    }


def _table(fn) -> list[dict]:
    try:
        df = fn()
    except Exception:
        return []
    if df is None or len(df) == 0:
        return []
    df = df.reset_index()
    df.columns = [str(c) for c in df.columns]
    return df.astype(object).where(df.notna(), None).to_dict("records")


def estimates(ticker: str) -> dict:
    """Consensus tables. Periods: 0q current quarter, +1q next, 0y current FY, +1y next FY."""
    t = yf.Ticker(_yf_symbol(ticker))
    out = {
        "earnings_estimate": _table(lambda: t.earnings_estimate),
        "revenue_estimate": _table(lambda: t.revenue_estimate),
        "eps_trend": _table(lambda: t.eps_trend),
        "eps_revisions": _table(lambda: t.eps_revisions),
        "growth_estimates": _table(lambda: t.growth_estimates),
        "recommendations": _table(lambda: t.recommendations_summary),
        "earnings_history": _table(lambda: t.earnings_dates.head(12) if t.earnings_dates is not None else None),
        "source": f"https://finance.yahoo.com/quote/{_yf_symbol(ticker)}/analysis",
    }
    for row in out["earnings_history"]:
        for k, v in row.items():
            if isinstance(v, (pd.Timestamp, datetime, date)):
                row[k] = str(v)[:10]
    return out


def _estimate(est: dict, table: str, period: str) -> float | None:
    for row in est.get(table, []):
        if row.get("period") == period:
            return row.get("avg")
    return None


def ntm(est: dict, fiscal_year_end: str | None, as_of: str, table: str = "earnings_estimate") -> float | None:
    """Next-twelve-months consensus: time-weighted blend of current and next fiscal year."""
    cur, nxt = _estimate(est, table, "0y"), _estimate(est, table, "+1y")
    if cur is None or nxt is None or not fiscal_year_end:
        return None
    fye = date.fromisoformat(fiscal_year_end)
    today = date.fromisoformat(as_of)
    remaining = min(max((fye - today).days, 0), 365) / 365
    return remaining * cur + (1 - remaining) * nxt


def peers(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for tk in tickers:
        try:
            rows.append(snapshot(tk))
        except Exception as exc:  # keep going; one bad ticker shouldn't sink the table
            rows.append({"ticker": tk.upper(), "error": str(exc)})
    cols = ["ticker", "name", "price", "market_cap", "enterprise_value", "ytd_return", "one_year_return",
            "trailing_pe", "forward_pe", "ev_ebitda", "dividend_yield", "beta", "roe", "roa", "sector",
            "industry", "hq", "summary"]
    df = pd.DataFrame(rows)
    return df[[c for c in cols if c in df.columns] + (["error"] if "error" in df else [])]


def multiples_history(prices: pd.DataFrame, quarterly: pd.DataFrame, filed: dict[str, str]) -> pd.DataFrame:
    """Weekly LTM P/E and EV/EBITDA using only data public as of each date (no look-ahead).

    `filed` maps quarterly period label -> filing date of that quarter's figures.
    """
    q = quarterly.sort_values("end").copy()
    q["ttm_eps"] = q["eps_diluted"].rolling(4).sum()
    q["ttm_ebitda"] = q["ebitda"].rolling(4).sum()
    q[["shares_diluted", "net_debt"]] = q[["shares_diluted", "net_debt"]].ffill()
    q["available"] = pd.to_datetime(pd.Series({p: filed.get(p) for p in q.index}))
    q = q.dropna(subset=["available"]).sort_values("available")
    weekly = prices["close"].resample("W-FRI").last().dropna().to_frame("price")
    rows = []
    for dt, price in weekly["price"].items():
        known = q[q["available"] <= dt]
        if known.empty:
            continue
        k = known.iloc[-1]
        pe = price / k["ttm_eps"] if k["ttm_eps"] and k["ttm_eps"] > 0 else np.nan
        ev = price * k["shares_diluted"] + (k["net_debt"] if pd.notna(k["net_debt"]) else 0)
        ev_ebitda = ev / k["ttm_ebitda"] if k["ttm_ebitda"] and k["ttm_ebitda"] > 0 else np.nan
        rows.append({"date": dt.date(), "price": price, "ltm_pe": pe, "ltm_ev_ebitda": ev_ebitda})
    return pd.DataFrame(rows).set_index("date")


def median_bands(mh: pd.DataFrame, col: str) -> dict:
    """Current value vs 1/2/3-year medians for a multiple series."""
    s = mh[col].dropna()
    if s.empty:
        return {}
    end = pd.Timestamp(s.index[-1])
    idx = pd.to_datetime(s.index)
    out = {"current": float(s.iloc[-1])}
    for years in (1, 2, 3):
        window = s[idx >= end - pd.DateOffset(years=years)]
        out[f"median_{years}y"] = float(window.median())
    return out
