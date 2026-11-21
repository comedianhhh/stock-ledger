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

### Foreign filers and ADRs

yfinance returns a foreign filer's statements in its reporting currency. TSM reports in TWD, but its quote is a USD ADS, and one ADS is 5 ordinary shares. Multiplying TWD earnings against a USD price used to inflate TSM's earnings yield by roughly 6x: about 33x from the currency, offset by the 5x ADS share count. That produced a fake P/E of 5.5x and a perfect value score.

The fix stays inside the existing boundaries:

- **Snapshot.** It records `financial_currency`, a daily FX series (`fx`, quote currency per reporting unit, with an inverse-pair fallback), and the ADS ratio `shares_per_price_unit`. The ratio is ordinary shares divided by Yahoo's market cap over price, measured once at fetch time.
- **`currency_bridge`.** It takes the last FX close on or before the as-of date, so back-dated runs stay point-in-time. `trim_to_asof` trims `fx` like any other price series.
- **Value factor.** Statement amounts are converted at that rate, and the point-in-time ordinary share count is divided by the ADS ratio. Quality and risk ratios are left alone, because they are currency-invariant.
- **Missing inputs.** If the rate or the ratio is missing, every valuation metric is `None` with a recorded reason. Coverage drops; nothing is guessed.
- **Older snapshots.** Snapshots without `financial_currency` (all fixtures and goldens) behave exactly as before.

Two simplifications are worth knowing. Flows such as EBIT and FCF are converted at the as-of spot rate rather than the fiscal-year average. The ADS ratio is also assumed constant over the snapshot's life. Neither changes the order of magnitude, which was the bug.

## 8. Settlement

`calls.jsonl` is append-only and idempotent on `ticker-asof-rulesversion`. `settle` regenerates all results from scratch, so they're always reproducible.

- Entry and exit prices both come from the freshly fetched, split- and dividend-adjusted series, never the recorded price. Total-return treatment is therefore consistent on both legs.
- A **hit** means a BUY beat SPY, or an AVOID lagged SPY. HOLD claims no edge and is excluded from the hit rate.

## 9. Macro odds are context, not a factor

`stockledger macro` adds a second I/O boundary (`macro.fetch`, Polymarket's public gamma API) with the same contract as the first. The fetch writes a trimmed raw snapshot, and `macro.build` is a pure function of that snapshot and the market set.

- **The market set is data.** It lives in `rules/macro_m1.yaml` with a version and a sha256, like the scoring rules. Dated events expire (a December FOMC resolves), so replacing a slug means bumping the version. A slug that is missing, closed or fails to fetch is reported per market and lowers `coverage`. It never aborts the run.
- **No arithmetic the data doesn't support.** `sum_p` and the modal outcome exist only when every live sub-market is `negRisk`, meaning the outcomes are mutually exclusive. A threshold ladder ("S&P touches 7,000 / 8,000") overlaps, so it gets neither. Overrounds such as `sum_p` of 1.05 are reported as-is rather than normalised away, because they show how loosely the event is priced.
- **Thin markets are labelled, not dropped.** Events below `min_volume_usd` carry `thin: true`. A narrative can still mention them, but only as direction.
- **Deliberately not a scoring input.** Folding odds into the factor score would make a stock's rating depend on which events happen to be listed that week. Instead, `--record` appends the day's odds to `ledger/macro.jsonl` (idempotent on date and set version), which lets the crowd be graded on its own later.

## Known limitations and next steps

- Only about 4–5 annual periods are available from yfinance, so there's no trailing-twelve-month data and no quarterly change.
- Value scores are absolute curves, not percentiles within a universe. A universe-relative version is the natural next step.
- Planned additions: Beneish M-score (manipulation screen), an earnings-surprise factor, and an LLM-graded eval of narrative quality (`claude plugin eval`) alongside the deterministic template eval.
