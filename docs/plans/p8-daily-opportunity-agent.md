---
plan: P8
title: Daily market-opportunity agent
status: active
opened: 2026-09-22
owner_decision: approved 2026-09-22
---

## Goal

Run one capital-disabled daily agent after the nightly data settles. Deterministic screening finds
unusual but liquid stocks and material market conditions; the model returns a structured
`ignore`, `watch`, `hold`, or `swing` assessment. Watches may carry a multi-day price trigger, but
only a fresh trigger-time reassessment can create a capped next-open order in one isolated paper
book.

## Scope

1. Rank a bounded candidate set from point-in-time daily return, overnight gap, relative volume,
   screen strength, earnings proximity, corporate actions, and market regime. Keep the formula and
   limits versioned, deterministic, and observable.
2. Accept optional public headline observations only when source, publication time, retrieval time,
   URL, exact text hash, and raw-response identity are retained. Missing or stale news is explicit.
3. Add a JSON-only model role that chooses `ignore`, `watch`, `hold`, or `swing` and supplies a
   horizon, confidence, thesis, invalidation, evidence IDs, and an optional bounded price alert.
4. Persist immutable daily runs, candidates, model attempts, assessments, alerts, and trigger-time
   reassessments. Replay returns the original terminal outcome without another model call.
5. Create one inactive isolated simulator book. A swing decision is deterministically sized within
   opening cash, liquidity, concentration, earnings, staleness, and exposure limits and fills only
   at a later session open. Sells may reduce only positions that book owns.
6. Add one daily user timer and one bounded read-only status projection showing freshness, model
   identity, candidate/decision counts, open/triggered/expired alerts, orders, fills, exposure,
   failures, and halt reasons.

## Not in scope

- Broker connectivity, credentials, live capital, margin, leverage, options, shorting, same-bar
  fills, model-selected quantity, model-written risk limits, unrestricted browsing, or social-media
  sentiment.
- Retrospective alerts, replaying missed trades, changing P7's monthly policies, pooling P7 and P8
  returns, or tuning thresholds after observing P8 performance.
- A claim of profitability from operational evidence. Promotion requires a separately frozen
  evaluation period and owner decision.

## Evaluation rule

The first review is after at least 90 calendar days and 60 completed market sessions. Operational
reliability, alert precision, turnover, costs, drawdown, and return versus SPY may be reported then,
but trade expectancy is not interpreted before 20 completed round trips. The detector thresholds,
model identity/prompt, sizing, and risk rules remain frozen throughout that cohort. No result grants
broker or real-capital authority.

## Done when

- A fixture-backed daily run deterministically ranks candidates, records one terminal assessment
  per candidate, replays without extra calls, and explicitly reports missing news.
- Alert fixtures prove below/above/cross trigger semantics, expiry, no same-day execution, fresh
  reassessment, duplicate suppression, and fail-closed malformed/model/data behavior.
- The isolated book cannot contaminate other portfolios and no broker route is importable or
  reachable from the pipeline.
- The timer/status surface, focused tests, full warnings-as-errors suite, static checks, and metrics
  budget are green before enablement.

## Budget

At most six implementation commits, each below 1,500 inserted non-data lines. New non-test code is
capped at 1,400 `server/` lines, 400 `engine/` lines, and 100 `sim/` lines. Prefer deletion and reuse.

## Risks

News can be late, duplicated, promotional, or unavailable; price moves can be bad prints; and a
daily model can overtrade noise. Deterministic admission, exact source timestamps, liquidity and
earnings gates, bounded candidates, alert confirmation, fresh reassessment, next-open fills, an
isolated book, and append-only attribution keep those risks observable and capital-disabled.
