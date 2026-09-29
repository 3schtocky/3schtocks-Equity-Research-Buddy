# 3schtocks Equity Research Buddy

An equity research agent for **Conscious Investments**. It runs inside [Claude Code](https://claude.com/claude-code): you screen stocks together, then it writes an **initiating coverage report** as a working-draft Word document. The narrative, number-dense format follows student-managed-fund initiations such as the Owl Fund's.

Author: Ethan Stott · stott@consciousinvestments.org

## How it works
- **Claude Code skills** (`.claude/skills/`) run the workflow: `screen` and `initiate`.
- **Python (`erb` CLI)** does everything that must be exact: SEC EDGAR and market data, the valuation model (DCF + multiples, bull/base/bear), charts, `.docx` assembly and a style/sourcing lint.
- **Guardrails:** every figure is sourced (filing, model or cited URL) or flagged `[VERIFY]`. Valuation numbers come only from the model, never from the LLM.

## Report structure
Cover (thesis bullets, rating, price targets, key stats, EPS table) · Table of Contents · Investment Summary · Industry Overview · Business Overview · Undervaluation & Thesis · Catalysts & Drivers · Risks to Investment Thesis (with mitigants) · Peer Group Analysis · Valuation Analysis · Financial Analysis · Appendix · Disclaimer

## Setup
```bash
uv sync
cp .env.example .env   # SEC requires a contact User-Agent
```
Build a facts pack from the command line:
```bash
uv run erb facts META          # coverage/META/facts/facts.md + CSVs + filing excerpts
uv run erb peers META GOOG SNAP PINS RDDT
uv run erb model META --init   # draft coverage/META/assumptions.yaml, then run the model
uv run erb model META          # rerun after editing assumptions
uv run pytest
```
Then open the repo in Claude Code and say, for example, "let's screen" or "initiate coverage on XYZ".

## Roadmap
- [x] Phase 0: scaffold, CLAUDE.md, style guide and section guides
- [x] Phase 1: data layer (`erb facts`, `erb peers`): EDGAR XBRL financials with provenance, segments, filing text, Yahoo market data and consensus
- [x] Phase 2: valuation model (`erb model`): DCF (stub + mid-year, PP&E roll-forward D&A), forward P/E and EV/EBITDA, bull/base/bear, rating, sensitivity, football field, comps, cover EPS table
- [ ] Phase 3: charts + .docx builder with Conscious Investments branding
- [ ] Phase 4: `initiate` skill + lint, end-to-end dry run
- [ ] Phase 5: quant screener + `screen` skill

## Disclaimer
Research drafts produced with this tool are for educational and informational purposes only and are not investment advice. See `guides/disclaimer.md`.

## License
MIT
