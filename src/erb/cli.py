"""`erb` command line entry point."""

from __future__ import annotations

import argparse
import sys


def cmd_facts(args) -> None:
    from . import facts

    facts.build(args.ticker, with_filings=not args.no_filings, refresh=args.refresh)


def cmd_peers(args) -> None:
    from . import market
    from .config import coverage_dir

    df = market.peers([args.ticker, *args.peers])
    path = coverage_dir(args.ticker) / "facts" / "peers.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    cols = [c for c in ("ticker", "name", "market_cap", "ytd_return", "one_year_return", "forward_pe", "ev_ebitda") if c in df]
    print(df[cols].to_string(index=False))
    print(f"Wrote {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="erb", description="3schtocks Equity Research Buddy")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("facts", help="Build the facts pack (EDGAR + market data) for a ticker")
    p.add_argument("ticker")
    p.add_argument("--no-filings", action="store_true", help="Skip filing text extraction")
    p.add_argument("--refresh", action="store_true", help="Bypass the daily EDGAR cache")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("peers", help="Market snapshot for a ticker and its peers")
    p.add_argument("ticker")
    p.add_argument("peers", nargs="+")
    p.set_defaults(func=cmd_peers)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
