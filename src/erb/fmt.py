"""Number formatting in house style (see guides/style_guide.md)."""

from __future__ import annotations

import math

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "TWD": "NT$", "CAD": "C$", "CHF": "CHF "}


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def pct(x, decimals: int = 1) -> str:
    """0.157 -> '15.7%', -0.202 -> '(20.2%)'."""
    if _bad(x):
        return "N/A"
    s = f"{abs(x) * 100:,.{decimals}f}%"
    return f"({s})" if x < 0 else s


def money(x, currency: str = "USD", decimals: int = 1) -> str:
    """1.1e12 -> '$1.1 tn', 7.9e11 -> '$790.0 bn', 8e8 -> '$800.0 mn', 3500 -> '$3.5k'."""
    if _bad(x):
        return "N/A"
    sym = SYMBOLS.get(currency, currency + " ")
    a = abs(x)
    for div, unit in ((1e12, " tn"), (1e9, " bn"), (1e6, " mn"), (1e3, "k")):
        if a >= div:
            s = f"{sym}{a / div:,.{decimals}f}{unit}"
            break
    else:
        s = f"{sym}{a:,.{decimals}f}"
    return f"({s})" if x < 0 else s


def price(x, currency: str = "USD") -> str:
    if _bad(x):
        return "N/A"
    return f"{SYMBOLS.get(currency, currency + ' ')}{x:,.2f}"


def multiple(x) -> str:
    return "N/A" if _bad(x) or x <= 0 else f"{x:,.1f}x"


def number(x, decimals: int = 1) -> str:
    if _bad(x):
        return "N/A"
    a = abs(x)
    for div, unit in ((1e9, " bn"), (1e6, " mn"), (1e3, "k")):
        if a >= div:
            s = f"{a / div:,.{decimals}f}{unit}"
            break
    else:
        s = f"{a:,.0f}"
    return f"({s})" if x < 0 else s


def fy(year: int, estimate: bool = False, actual: bool = False) -> str:
    """2025 -> "FY'25" (optionally FY'25E / FY'25A)."""
    return f"FY'{year % 100:02d}" + ("E" if estimate else "A" if actual else "")


def quarter(year: int, q: int) -> str:
    """(2025, 3) -> "3Q'25"."""
    return f"{q}Q'{year % 100:02d}"
