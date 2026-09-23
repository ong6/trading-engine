# Agent Backtesting Roadmap

## Recommendation

Credible agent backtesting needs point-in-time data, a horizon-appropriate execution model, and one
frozen evaluation contract. The simulator and safety boundary are strong, but historical
fundamentals/news are absent and agent evidence has been split between DuckDB and JSONL files. P11
starts a canonical trace and delayed-label dataset now so each future decision becomes reusable.

## Current gaps

### Data

- Historical prices use today's surviving symbols; delisted names and old memberships are missing.
- Point-in-time fundamentals and timestamped news begin in 2026.
- Agent-visible intraday quotes now retain exact response receipts and bitemporal normalized bars;
  the broad nightly archive still uses its legacy DataFrame-only collector.
- Stable security/issuer identity and revision-aware symbol history remain incomplete.

Every fact should carry entity/security ID, event time, publication time, availability time,
ingestion time, immutable revision, raw and normalized hashes, source version, and license class.
Replay joins must use availability time at or before the decision cutoff.

### Execution

The close-decision/next-open model is suitable for swing trading. It includes adverse
spread/slippage, participation, fees, gap and missing-bar handling, and deterministic limits. P8
now freezes maximum-hold and close-below-signal-low exits, generates their orders after the close,
and records decision/tool/order latency, session-level order-to-fill latency, and arrival/open/fill
shortfall. Sub-day fill latency remains unavailable because the simulator records a session date.

Intraday policies should remain shadow-only until quote/trade data supports bid/ask, latency,
partial fills, liquidity consumption, cancel latency, and passive-order queue position. OHLC bars
cannot establish the path within a bar.

### Evaluation

Every trace should bind policy/cadence/prompt/model/tool versions; event, cutoff, and completion
times; exact inputs/outputs and source references; request/response IDs; latency/tokens; terminal
status; per-ticker decisions; and execution authority. Tool attempts, orders, fills, costs, and
equity link to the originating trace without changing it.

Labels are appended only after 1, 5, 10, or 20 later sessions exist. They contain entry/exit prices,
asset and SPY returns, excess return, adverse/favorable excursion, and price-prefix identity. Labels
must never be available to the decision policy.

Evaluate frozen variants on paired windows using coverage, failures, abstention, directional
accuracy, calibration/Brier score, forecast error, excess return, excursion, turnover, costs,
implementation shortfall, latency, tokens, and alert precision. Resample decision windows, not bars.

## Historical data programme

- Sharadar SEP/SF1 remains the preferred paid candidate for prices, delistings, corporate actions,
  reference history, fundamental date keys, dimensions, and update history.
- Compare Norgate on membership history, delistings, and local-use licensing.
- Ingest SEC EDGAR independently. Store CIK, accession, filing date, exact acceptance timestamp,
  form, reporting period, and raw filing/XBRL identity. Report period is not availability time.
- Audit historical-news vendors such as Polygon, Alpaca, and FMP for archive depth, publication and
  update/delete timestamps, stable article/entity IDs, correction semantics, pagination, raw
  retention, and model/backtest licensing.
- Use point-in-time security-master/corporate-action semantics such as Databento documents as a
  benchmark even if another vendor is selected.

## LLM contamination controls

Historical tests need named versus symbol/date-blinded prompts, post-training-cutoff prospective
cohorts, date-only recall probes, synthetic or perturbed series, prompt-order permutations, frozen
model variants, and deterministic controls using identical data and costs. Prospective post-cutoff
evidence remains the only promotion-quality result.

Research on look-ahead propensity finds that historical financial accuracy can decay sharply beyond
memorized training windows. Blinding symbols helps but cannot hide famous events or exact price paths.

## Phases

### A. Accumulate now

- Complete P11 canonical traces and maturity-gated labels.
- Extend exact-response capture from the bounded agent quote set to the broad nightly archive only
  when the provider adapter can do so without duplicating requests or weakening rate controls.
- Link tools, orders, fills, costs, positions, and equity to traces.
- Alert on missing windows, source latency, identity drift, and incomplete labels.
- Freeze P8/P9 for 90 days/60 sessions and at least 20 completed trades.

### B. Historical data

- Set separate initial and recurring spend ceilings.
- Trial Sharadar versus Norgate and add SEC EDGAR acceptance-time evidence.
- Select historical news only after timestamp, revision, and license review.
- Recalculate readiness without silently mixing datasets.

### C. Execution

- Enforce maximum-hold and executable invalidation exits.
- Record latency stages and implementation shortfall.
- Calibrate spread/impact from paper or quote evidence.
- Build quote-level replay only for genuinely intraday policies.

### D. Evaluation

- Freeze datasets, prompts, models, graders, and sample gates.
- Pair each agent policy with deterministic and cash controls.
- Separate selection quality from execution quality.
- Require post-cutoff prospective evidence before promotion.

## References

- [SEC EDGAR APIs](https://www.sec.gov/edgar/sec-api-documentation)
- [Sharadar SF1](https://data.nasdaq.com/databases/SF1/documentation)
- [Sharadar SEP](https://data.nasdaq.com/databases/SEP/documentation)
- [Databento corporate actions](https://databento.com/docs/api-reference-reference/corporate-actions)
- [Feast point-in-time joins](https://docs.feast.dev/v0.43-branch/how-to-guides/feast-snowflake-gcp-aws/build-a-training-dataset)
- [MLflow agent evaluation](https://mlflow.org/docs/latest/genai/eval-monitor)
- [NautilusTrader fill and matching](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-prices-and-matching/)
- [QuantConnect slippage models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/supported-models)
- [Look-Ahead-Bench](https://arxiv.org/html/2601.13770v1)
- [Detecting Lookahead Bias in LLM Forecasts](https://arxiv.org/html/2512.23847)

## Decision needed

The immediate engineering priority is P11. The next owner decision with the greatest research
leverage is a P3 spend ceiling for Sharadar or equivalent PIT data. Historical news needs a separate
budget and licensing review. Do not expand strategy count or execution authority before these
foundations create stable prospective cohorts.
