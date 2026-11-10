# {{ name }} ({{ ticker }}) — stockledger report, as of {{ asof }}

> **Rating: {{ action.final }}** · score {{ score.total }} / 100 · rules {{ rules.version }}
> Raw rating before guardrails: {{ action.raw }} · data coverage {{ score.coverage | pct }}

<!-- Replace this comment with 2-3 sentences: what the company does and the single most
important reason for the rating. Words only; every number must be a placeholder. -->

## Scorecard

| Dimension | Score (0-100) |
|---|---|
| Quality | {{ score.dimensions.quality.score }} |
| Value | {{ score.dimensions.value.score }} |
| Momentum | {{ score.dimensions.momentum.score }} |
| Risk (higher = calmer) | {{ score.dimensions.risk.score }} |

<!-- List any guardrail with "triggered": true from action.guardrails and explain it in words,
e.g. "Capped at HOLD: price is below its 200-day average". If none fired, say so. -->

## Quality

- Piotroski F-score: {{ quality.piotroski.score }} of {{ quality.piotroski.evaluated }} checks passed
- Gross profit / assets: {{ quality.gross_profitability | pct }}
- Return on capital (Greenblatt): {{ quality.return_on_capital | pct }}
- Gross margin: {{ quality.gross_margin | pct }} · revenue growth: {{ quality.revenue_growth | pct }}

<!-- Interpret: which Piotroski checks failed (quality.piotroski.checks.*) and what that says. -->

## Value

- Earnings yield ({{ value.basis }}): {{ value.earnings_yield | pct }}
- Free-cash-flow yield: {{ value.fcf_yield | pct }}
- P/E: {{ value.pe | x }} · market cap: {{ value.market_cap | usd_b }}

## Trend & momentum

- Price {{ price.price | usd }} vs 200-day average {{ price.ma200 | usd }} ({{ price.price_vs_ma200 | pct }})
- 12-1 month momentum: {{ price.momentum_12_1 | pct }}, vs SPY: {{ price.relative_momentum_12_1 | pct }}
- Extension above 50-day average: {{ price.extension_atr | num }} ATRs

## Risk

- Altman Z'': {{ risk.altman_z2.value | num }} ({{ risk.altman_z2.zone }} zone)
- 1-year volatility: {{ price.volatility_1y | pct }} · max drawdown: {{ price.max_drawdown_1y | pct }}

## Bull case / Bear case

<!-- 2-4 bullets each. Qualitative context (business model, moat, competition, recent news)
is welcome here, but no hand-typed numbers: cite placeholders or describe in words. -->

## What would change the rating

<!-- Concrete, checkable conditions tied to metrics, e.g. "a close back above the 200-day
average would lift the below_trend cap". -->

## Analyst note (optional)

<!-- If you disagree with the rules-based rating, say why here. The rating above does not change. -->

---
*Numbers computed by stockledger from yfinance data; every figure above is filled in by
`stockledger render`, not typed by the model. Educational use only, not investment advice.*
