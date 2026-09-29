# Cover Page

**Purpose:** The whole pitch on one page. A reader who stops here knows the thesis, the rating and the upside.

**Layout** (built by `erb build`; you supply the content in `sections/00_cover.md`):
- Header: Conscious Investments logo, report date ("27 October 2025" format), "Initiating Coverage Report".
- Title block: "Company Name (TICKER)" plus a one-line exclamatory pun tagline.
- **Left column: 4–5 thesis bullets**, each 3–5 lines:
  1. Recent stock performance (YTD return) and the controversy or misunderstanding that creates the opportunity.
  2–4. One bullet per thesis pillar, each with at least one hard number.
  5. The closing bullet: "We initiate with an **Outperform** rating and a base-case price target of $X, implying Y% upside over our 12–18 month horizon." (All figures from `model.json`.)
- **Company Overview paragraph** (4–6 sentences): what it does, scale, founding and history, segments, next earnings date.
- **Right sidebar (auto from model.json + market data):** price scenario box (Bear, Current, Base PT, Bull with returns), rating; Symbol (EXCHANGE: TICKER), 52-week range, YTD performance, market cap, dividend yield, NTM P/E, NTM EV/EBITDA, ROE, ROA, ROIC; quarterly EPS table (last FY actual, current FY estimate, next FY estimate, with YoY change); analyst block: Ethan Stott, stott@consciousinvestments.org.
- Footer: source line and a short conflict/holdings note.
