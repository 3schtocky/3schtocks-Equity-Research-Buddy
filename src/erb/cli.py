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


def cmd_model(args) -> None:
    from . import valuation
    from .config import coverage_dir

    path = coverage_dir(args.ticker) / "assumptions.yaml"
    if args.init:
        if path.exists() and not args.force:
            sys.exit(f"{path} exists; edit it, or pass --force to overwrite it")
        path.write_text(valuation.draft_assumptions(args.ticker))
        print(f"Wrote {path}")
    valuation.run(args.ticker)


def cmd_charts(args) -> None:
    from . import charts

    charts.render_all(args.ticker)


def cmd_scaffold(args) -> None:
    from . import scaffold

    scaffold.scaffold(args.ticker, sample=args.sample, force=args.force)


def cmd_build(args) -> None:
    from . import docx_build

    if not args.no_charts:
        from . import charts

        charts.render_all(args.ticker)
    out = docx_build.build(args.ticker, update_on_open=not args.word)
    if args.word:
        from . import word

        word.finalize(out)


def cmd_lint(args) -> None:
    from . import lint

    sys.exit(lint.report(args.ticker))


CORE = {"min_cap": 2.0, "weights": "0.15,0.40,0.30,0.15"}   # Ethan's saved screen (2026-09-29)


def cmd_screen(args) -> None:
    from datetime import date

    if args.preset == "gems":
        from . import gems

        as_of = date.fromisoformat(args.as_of) if args.as_of else None
        gems.run(top=args.top, as_of=as_of, refresh=args.refresh)
        return
    from . import screen

    if args.as_of:
        sys.exit("--as-of is only supported with --preset gems")
    min_cap, weights = args.min_cap, args.weights
    if args.preset == "core":
        min_cap, weights = CORE["min_cap"], CORE["weights"]
    w = dict(zip(("value", "quality", "growth", "momentum"), (float(x) for x in weights.split(","))))
    screen.run(min_cap=min_cap * 1e9, top=args.top, weights=w)


def cmd_memo(args) -> None:
    from pathlib import Path

    from . import memo

    run_dir = Path(args.screen) if args.screen else None
    for t in args.tickers:
        memo.build(t, run_dir=run_dir, model=not args.no_model)


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

    p = sub.add_parser("model", help="Run the valuation model (DCF, multiples, scenarios, rating)")
    p.add_argument("ticker")
    p.add_argument("--init", action="store_true", help="Draft assumptions.yaml from the facts pack first")
    p.add_argument("--force", action="store_true", help="With --init, overwrite existing assumptions")
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("charts", help="Render report charts from model.json and the facts pack")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_charts)

    p = sub.add_parser("scaffold", help="Write sections/*.md skeletons with exhibit tokens")
    p.add_argument("ticker")
    p.add_argument("--sample", action="store_true", help="Fill with marked layout filler text")
    p.add_argument("--force", action="store_true", help="Overwrite existing section files")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("build", help="Build the .docx report (renders charts first)")
    p.add_argument("ticker")
    p.add_argument("--no-charts", action="store_true", help="Reuse existing charts")
    p.add_argument("--word", action="store_true", help="Use Microsoft Word to refresh the TOC and export a PDF")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("lint", help="Style and sourcing checks on sections/*.md (exit 1 on errors)")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("screen", help="Rank US-listed stocks on value, quality, growth and momentum")
    p.add_argument("--min-cap", type=float, default=2.0, help="Minimum market cap in $ bn (default 2)")
    p.add_argument("--top", type=int, default=30, help="Rows in screen.md (default 30)")
    p.add_argument("--weights", default="0.30,0.30,0.20,0.20", help="value,quality,growth,momentum")
    p.add_argument("--preset", choices=["gems", "core"],
                   help="gems: $0.3-15bn names at a growth inflection; core: Ethan's saved screen")
    p.add_argument("--as-of", help="Gems only: run as of a past date (YYYY-MM-DD) with data public then")
    p.add_argument("--refresh", action="store_true", help="Gems only: re-download today's prices")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("memo", help="Pitch memo skeleton(s) for screened tickers")
    p.add_argument("tickers", nargs="+")
    p.add_argument("--screen", help="Screen run folder (default: the latest)")
    p.add_argument("--no-model", action="store_true", help="Leave the valuation out of the memo")
    p.set_defaults(func=cmd_memo)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
