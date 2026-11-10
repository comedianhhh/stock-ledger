# Architecture & design decisions

```
 yfinance ──► snapshot.json ──► factors (pure) ──► score ──► action ──► guardrails ──► metrics.json
   (I/O)        (frozen)                                                                  │
                                                                                          ▼
                     Claude (skill) ──► report.template.md ──check──► render ──► report.md
                                                                                          │
                                         ledger/calls.jsonl ◄──record─────────────────────┘
                                                │
                       yfinance closes ──► settle ──► settlements.jsonl + TRACK_RECORD.md
```

## 1. One I/O boundary, then pure functions

Only `snapshot.fetch` and `ledger.yfinance_closes` touch the network. Everything else is a pure function of a JSON snapshot. This has three consequences:

- Tests run offline against recorded snapshots (`tests/fixtures/`). Golden tests pin the full `metrics.json` output, so any drift in a factor shows up as a reviewable diff.
- Any past analysis can be reproduced bit-for-bit with `analyze --snapshot`.
- Market cap and EV are **rebuilt** from shares × snapshot price, not read from yfinance's live `info`. Otherwise a back-dated snapshot would silently use today's valuation.

## 2. Point-in-time discipline (`trim_to_asof`)

yfinance doesn't provide filing dates. An annual statement only becomes visible when `period_end + 90 days <= asof`, and prices after `asof` are dropped.

This is conservative but imperfect. yfinance data is restated and survivorship-biased. That's why backfilled calls are labelled `backfill` and reported separately from `live` calls, and never presented as forward evidence.

## 3. Citation by construction, instead of hallucination detection

The usual approach is to let the LLM write numbers, then try to verify them. Here the model never writes them at all:

- It cites `{{ path | format }}` placeholders.
- `check` rejects decimals, percentages, `$` amounts and multiples typed by hand.
- `render` fills in the values.

Plain integers ("200-day", "FY2025") are allowed so the prose stays natural. Inline code is exempt.

The trade-off is that external numbers (for example, a figure from a news article) can't appear in the report. That is deliberate: anything in the report is either computed or clearly qualitative.

`tests/test_template.py` is the eval that keeps the shipped template valid against every golden metrics file. That includes a bank with null EV and a distressed loss-maker.

## 4. Rules are data, not prompts

Every weight, curve and threshold is in `rules/v1.yaml`. Its sha256 is stamped into each `metrics.json` and each ledger call, so a track record can always be attributed to an exact rule set.

Compare this to systems where strategies are prompt text interpreted by an LLM. Those can't be unit-tested, and they don't give the same answer twice.

## 5. Missing data lowers confidence, not the score

A missing input is `None`, never 0:

- Piotroski reports `score / evaluated`.
- The scoring step drops missing components, renormalises the remaining weights, and reports `coverage`.
- When coverage falls below 60%, a guardrail caps the rating at HOLD.

## 6. Guardrails only downgrade

The score decides how attractive a stock is. Guardrails encode "don't do something dumb": buying below the 200-day average, chasing a stock more than 4 ATRs above its 50-day average, or holding a distressed balance sheet. Because they can only cap, they can never manufacture a BUY.

The distress guardrail requires **both** a distress-zone Altman Z'' **and** a weak Piotroski score. Z'' alone can misfire on healthy companies that have bought back so much stock that their retained earnings are negative and their working capital is near zero.

## 7. Sector exceptions

- **Banks and insurers:** EV, FCF, gross profitability and ROC are meaningless, because debt is their raw material. They get E/P, and the missing quality inputs show up as reduced coverage.
- **Altman Z'':** returns `n/a` for financials and real estate.

The Z'' variant was chosen over the 1968 Z for all other companies because it drops the industry-dependent sales/assets term.

## 8. Settlement

`calls.jsonl` is append-only and idempotent on `ticker-asof-rulesversion`. `settle` regenerates all results from scratch, so they're always reproducible.

- Entry and exit prices both come from the freshly fetched, split- and dividend-adjusted series, never the recorded price. Total-return treatment is therefore consistent on both legs.
- A **hit** means a BUY beat SPY, or an AVOID lagged SPY. HOLD claims no edge and is excluded from the hit rate.

## Known limitations and next steps

- Only about 4–5 annual periods are available from yfinance, so there's no trailing-twelve-month data and no quarterly change.
- Value scores are absolute curves, not percentiles within a universe. A universe-relative version is the natural next step.
- Planned additions: Beneish M-score (manipulation screen), an earnings-surprise factor, and an LLM-graded eval of narrative quality (`claude plugin eval`) alongside the deterministic template eval.
