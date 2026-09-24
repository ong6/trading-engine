# Agent trading review - 2026-09-22

## Executive verdict

The box now has a bounded agent research and simulator path. It runs one authoritative end-of-day
opportunity process plus two higher-frequency shadow observers. The selected model is
GPT-5.6-Sol:max, not a model literally named nightly. The nightly model may recommend trades and
confirm one typed submit_paper_trade intent. Deterministic code controls admission, size, risk,
idempotency, portfolio isolation, and next-session-open fills. No broker route or real capital exists.

The implementation is ready to collect prospective paper evidence, but it has not demonstrated an
edge. Its first live EOD run produced five assessments and two watches; one proposed swing was not
retroactively traded. A small 2022 replay looks positive but is contaminated and non-promotable.

## Running architecture

Nightly data feeds deterministic standout ranking and retained news. The model classifies each
candidate as ignore, hold, watch, or swing. A watch becomes an append-only multi-day alert. A later
real-bar crossing forces a fresh assessment. A swing then requires a separate exact tool call, which
is durably recorded before deterministic risk and sizing can create an isolated simulator order.
Only the normal simulator may fill it, at a later session open.

| Variant | Schedule | Role | Order authority |
|---|---|---|---|
| Hourly watch | 09:15-16:15 New York, weekdays | rapid quote/headline reassessment | none |
| Four-hour review | 09:30 and 13:30 New York, weekdays | catalyst/structure review | none |
| Nightly opportunity | 02:00 UTC Tuesday-Saturday | completed-EOD swing decision | isolated simulator only |
| Gap-volume plus AI | nightly paired projection | deterministic candidate and model allow/veto | shadow only |

## Controls and failure behavior

- Candidates are active, liquid, non-ETF stocks with real bars and at least 21 sessions.
- Ranking uses daily move, overnight gap, relative volume, screen novelty, and relative strength.
- Exact bounded Yahoo headline responses and timestamps are retained. Missing news is explicit.
- The model must assess every candidate once; malformed, missing, duplicate, or unsupported output fails.
- Alerts stay within 30% of observed close and expire after 1-10 completed sessions. Triggering an
  alert never creates an order by itself.
- Held positions are forced into the next daily review and require an explicit hold-or-sell answer.
- The trade tool cannot specify quantity, account, price, broker, or risk limits.
- Tool calls are locked and saved before consumption. Replay resumes without another model call and
  cannot duplicate an attributed order.
- Buys require risk-on regime, template pass, confidence at least 0.65, no earnings within five days,
  no quarantine, no duplicate pending order, at most three positions, and 10% sizing.
- Orders are long-only and simulator-only. The pre-open cutoff prevents stale decisions from trading.

## Live evidence

The first EOD run for 2026-09-21 retained five assessments: CRML and SECZ were ignored, GRAL and WBD
became watches, and NUAI was classified as a seven-session swing buy. The deterministic gap-volume
candidate also selected NUAI and the comparison recorded allow. The isolated book was inactive for
that run, so no order was created. It was activated afterward with US$10,000 simulated cash, zero
positions, and zero pending orders. The first hourly and four-hour services completed successfully.

## 2022 retrospective diagnostic

The database has 251 sessions across 3,589 currently listed symbols in 2022, but no point-in-time
2022 fundamentals and no timestamped 2022 news. Only price-derived variants ran; missing variants
were recorded as unavailable rather than reconstructed with current information.

Four dates and AAPL/MSFT/XOM/cash were frozen before inference. Both named and symbol-blinded variants
selected XOM on all four dates. After 20 bp round-trip costs, each was correct on 3/4 windows, returned
+4.78% per window on average, compounded to +19.78%, had -8.20% maximum within-window drawdown, and
averaged +5.85 percentage points over SPY. Mean absolute forecast error was 5.13 points named and
5.45 points blinded.

This is not evidence of predictive alpha. The model may remember 2022; assets and dates were selected
with hindsight; the current-symbol universe is survivor-biased; and four observations have no power.
Identical named/blinded choices show only that removing labels did not change this tiny sample.

## Existing algorithm evidence

The broader engine remains an evidence appliance, not a proven profitable suite. Recent league
leaders have attractive short-window returns, but the current walk-forward cohort finds no robust
winner over its proper control. Most recently tested timing ideas were rejected. Sector momentum and
E1 are immature forward records; XS momentum has not reached its first forward fill. The new
gap-volume candidate is a frozen forward comparator and cannot be tuned from its first observation.

## Remaining priorities

1. Accumulate 60 sessions and 90 calendar days of P8/P9 evidence; require 20 completed trades before
   estimating trade expectancy.
2. Add persisted hourly/four-hour freshness and paired prompt metrics to the API status projection.
3. Add deterministic maximum-hold and invalidation exit enforcement before real-capital discussion.
4. Rehearse P8/P9 backup and restore after the first real order/fill lifecycle.
5. Acquire audited historical point-in-time fundamentals/news before further historical model tests.
6. Complete P7 separately; P8/P9 evidence must not substitute for its equal-capital paired cohort.

## Verification

- Full warnings-as-errors Python suite and Ruff checks passed.
- The dedicated P8/P9 self-test passed using temporary databases.
- A real typed-tool transport probe returned exactly one expected call with exact arguments.
- A verified recovery bundle was created before production schema changes.
- Metrics and all approved source budgets are green.
