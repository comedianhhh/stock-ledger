# stock-ledger

**A Claude Code plugin for US stock analysis where the code owns the numbers, the LLM owns the explanation, and every call is graded against SPY.**

Most LLM stock analyzers let the model fetch, compute and opine in one breath. That mixes up three questions: are the numbers right, is the reasoning sound, and did it work? stock-ledger answers each one separately:

| Concern | Owned by | Guarantee |
|---|---|---|
| Numbers (factors, score, BUY/HOLD/AVOID) | `stockledger` Python CLI | Pure functions of a saved snapshot, covered by unit and golden tests, versioned rules |
| Narrative (why, bull/bear, what would change it) | Claude, via the skill | **Citation by construction**: the model writes `{{ value.earnings_yield \| pct }}`, never `5.8%`. `check` rejects hand-typed numbers |
| Did it work? | `ledger/` | Append-only call log, settled against SPY at 63/126/252 trading days in [`TRACK_RECORD.md`](ledger/TRACK_RECORD.md) |

No API key is needed. It runs on your Claude Code subscription plus free yfinance data.

> Educational and research use only. Not investment advice.

## Quick start

```bash
# 1. install the CLI
uv tool install git+https://github.com/comedianhhh/stock-ledger

# 2. install the Claude Code plugin
/plugin install stock-ledger --marketplace comedianhhh/stock-ledger
```

Then, in Claude Code, ask:

> analyze AAPL

Claude runs `stockledger analyze AAPL`, writes a report template, runs `check` until it passes, renders the report, and records the call.

You can also use the CLI on its own:

```bash
stockledger analyze AAPL                      # -> out/AAPL_<date>.metrics.json
stockledger analyze AAPL --asof 2025-06-30    # point-in-time replay
stockledger check  report.template.md --metrics out/AAPL_<date>.metrics.json
stockledger render report.template.md --metrics out/AAPL_<date>.metrics.json -o report.md
stockledger record out/AAPL_<date>.metrics.json
stockledger settle                            # regrade all calls -> ledger/TRACK_RECORD.md
```

## What gets scored (rules v1)

| Dimension | Weight | Factors | Source |
|---|---|---|---|
| Quality | 35% | Piotroski F-score (9 checks), gross profit / assets, Greenblatt return on capital | Piotroski 2000; Novy-Marx 2013; Greenblatt 2005 |
| Value | 25% | EBIT / EV, FCF yield (E/P for financials) | Greenblatt; Gray & Carlisle |
| Momentum | 25% | 12-1 month return vs SPY, price vs 200-day average | Jegadeesh & Titman 1993; Faber 2007 |
| Risk | 15% | 1-year volatility, max drawdown | Ang et al. 2006 |

**Guardrails** can only downgrade a rating, never upgrade it. Each one records its reason:

- `below_trend`: price under its 200-day average, capped at HOLD.
- `overextended`: price more than 4 ATRs above its 50-day average, capped at HOLD.
- `distress`: Altman Z'' in the distress zone and Piotroski score of 3 or less, capped at AVOID.
- `low_coverage`: less than 60% of inputs available, capped at HOLD.

All thresholds live in [`rules/v1.yaml`](src/stockledger/rules/v1.yaml). Each output carries the rules version and the file's sha256.

## Example

```
$ stockledger analyze BYND
BYND asof 2026-11-10: score 1.17 (coverage 100%) -> AVOID -> AVOID [guardrails: below_trend, distress]
  quality   3.33
  value     0.0
  momentum  0.0
  risk      0.0
```

A full Claude-written, `render`-filled report for MSFT is produced by the skill in about a minute. The rendered report contains 33 cited values and zero hand-typed numbers.

### The track record is honest, including when it's bad

[`ledger/TRACK_RECORD.md`](ledger/TRACK_RECORD.md) currently holds 15 *backfilled* calls, all as of 2025-06-30. The 252-day AVOID bucket shows +214% average excess return, driven by Intel's 2025 rally. In other words, the AVOID call on Intel was badly wrong.

That's the point of the ledger: the scores are published whether or not they flatter the model. Fifteen calls is far too few to conclude anything. Backfilled calls are kept apart from live calls and are not evidence of forward performance.

## Project layout

```
src/stockledger/
  snapshot.py      the only network I/O: yfinance -> JSON snapshot; trim_to_asof()
  factors/         pure functions: quality, value, risk, price
  scoring.py       metrics -> score -> action -> guardrails
  render.py        placeholder check/render (citation by construction)
  ledger.py        append-only calls, settlement vs SPY, TRACK_RECORD.md
  rules/v1.yaml    every weight and threshold
skills/stock-analysis/   the Claude Code skill + report template
tests/                   unit tests, golden snapshot tests, template eval
```

The design decisions and trade-offs are written up in [ARCHITECTURE.md](ARCHITECTURE.md).

## Development

```bash
uv sync
uv run pytest                                   # offline: recorded fixtures, no network
UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py   # after an intentional factor/rules change
```

## License

MIT.
