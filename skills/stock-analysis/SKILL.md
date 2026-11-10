---
name: stock-analysis
description: Rules-based US stock analysis with a public, self-grading track record. Use when the user asks to analyze, rate, or compare US stock tickers (e.g. "analyze AAPL", "is MSFT a buy", "compare NVDA vs AMD", "update my track record"). Numbers come from the deterministic `stockledger` CLI; Claude writes the narrative and never types figures itself.
---

# Stock analysis (stockledger)

The division of labour is strict:

- **`stockledger` (code) owns every number and the rating.** Factors, score, BUY/HOLD/AVOID and guardrails are computed deterministically from a saved data snapshot.
- **You own the explanation.** You interpret the metrics, add qualitative context, and argue the bull and bear case. You never type a figure, and you never change the rating.

## 0. Make sure the CLI exists

Run `stockledger --help`. If the command is not found, tell the user it needs installing and suggest one of these:

- `uv tool install git+https://github.com/comedianhhh/stock-ledger`
- `uv tool install -e <path-to-repo>`

Run every command from the user's working directory. Outputs go to `./out/` and the ledger to `./ledger/`.

## 1. Compute

```
stockledger analyze <TICKER>                 # live data
stockledger analyze <TICKER> --asof YYYY-MM-DD   # only info knowable on that date
```

This writes `out/<TICKER>_<ASOF>.metrics.json` (plus the raw snapshot) and prints the score. Read the metrics file. It is the only source of truth for numbers.

If it fails (unknown ticker, no data), report the error. Do not fall back to web-searched numbers.

## 2. Gather qualitative context (optional)

You may web-search for business model, competitive position and recent news. Use this only to explain *why*. Numbers you find on the web cannot appear in the report (see step 4).

## 3. Write the report template

Copy the structure from `references/report-template.md` into `out/<TICKER>_<ASOF>.report.template.md` and fill in the commented sections in prose.

Placeholder syntax: `{{ path.to.leaf | format }}`
- Paths are keys in metrics.json, e.g. `quality.piotroski.score` or `price.ma200`.
- Formats:
  - `pct`: 0.0583 → 5.8%
  - `x`: 25.0x
  - `usd`: $348.76
  - `usd_b`: $2,500.0B
  - `num`: 1.23
  - `int`: 1,234
  - no format: raw value

Rules:
- Every decimal, percentage, dollar amount or multiple must be a placeholder. Plain integers in words ("200-day", "12-1 momentum", "FY2025") are fine.
- Explain any guardrail with `"triggered": true` in `action.guardrails`.
- Explain failed Piotroski checks, using `quality.piotroski.checks.*`.
- Where a metric is `null`, say it is unavailable and why (for example, EV is not meaningful for banks). Don't estimate it.

## 4. Check, fix, render

```
stockledger check  out/<T>_<ASOF>.report.template.md --metrics out/<T>_<ASOF>.metrics.json
stockledger render out/<T>_<ASOF>.report.template.md --metrics out/<T>_<ASOF>.metrics.json -o out/<T>_<ASOF>.report.md
```

`check` fails on unknown paths, bad formats, or hand-typed numbers. Fix the template and re-run until `"ok": true`; `render` refuses otherwise. Show the user the rendered report (or a summary plus its path).

## 5. Record the call

```
stockledger record out/<T>_<ASOF>.metrics.json
```

This appends the rating to `ledger/calls.jsonl` and is idempotent. Calls with an old `--asof` are tagged `backfill` and reported separately from `live` calls. Tell the user the call was recorded. Skip this step if they asked not to track it.

`stockledger settle` grades every past call against SPY at 63, 126 and 252 trading days and regenerates `ledger/TRACK_RECORD.md`. Run it when the user asks how past calls did.

## Comparisons

Run `analyze` for each ticker and compare dimension scores side by side, using one template per ticker or a combined table of placeholders.

Placeholders resolve against a single metrics file. For a combined report, render each section separately, or describe the differences in words.

## Never

- Change, soften or "override" `action.final` in the headline. Disagreement goes in the "Analyst note" section.
- Present numbers from memory or the web as stockledger output.
- Give personalised financial advice. The report ends with the educational-use disclaimer.

## Reference

- `references/report-template.md`: the report skeleton (it passes `check` against any metrics file).
- `references/fundamental-analysis.md`, `references/financial-metrics.md`: qualitative frameworks for the narrative sections.
