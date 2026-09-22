---
plan: P10
title: Contamination-aware 2022 agent replay
status: active
opened: 2026-09-22
owner_decision: approved 2026-09-22
---

## Goal

Measure how the current frozen model behaves on four preregistered 2022 decisions when given only
information available in the local store on each date. Compare its 20-session directional calls
and next-open paper returns with fixed controls while explicitly treating the result as contaminated
retrospective behavior, not evidence that the agent would have predicted 2022 in real time.

## Scope

- Fixed assets: AAPL, MSFT, XOM, and cash, with SPY as market context. Fixed decision dates are the
  last stored sessions of January, April, July, and October 2022.
- One model choice per date selects AAPL, MSFT, XOM, or cash for 20 sessions. Price-only prompts
  contain trailing returns, volatility, drawdown, moving averages, and volume through the decision.
- Future bars are loaded only after the response is saved. Entry is the next session open; exit is
  the twentieth later-session close; baseline_v1 costs apply on both sides.
- Publish directional accuracy, return, drawdown, turnover, costs, and SPY-relative results. Mark
  fundamentals and historical-news variants unavailable because their local snapshots begin in 2026.
- Retain exact request/model/response identity and a data-prefix hash. Reruns use saved responses.

## Not in scope

- Calling this out-of-sample, using current fundamentals or recent search results as 2022 facts,
  claiming alpha, tuning dates/symbols/prompts, or promoting results to P8/P9.
- Broker orders, real capital, live portfolio mutation, or writes to production DuckDB.

## Done when

- Four frozen decisions and mechanically delayed returns are published with unavailable variants
  and explicit training-memory and survivorship-bias disclosures.
- A second run makes zero model calls and reproduces identical metrics from retained decisions.
- Focused/full tests, static checks, and metrics budget pass.

## Budget

Two commits, each below 1,500 inserted non-data lines; at most 500 new farm lines. No server,
engine, simulator, or tools ceiling increase.

## Risks

The model may recall 2022, the current symbol universe omits historical failures, and four windows
have no statistical power. Fixed dates and symbols, delayed outcome access, exact retained prompts,
and diagnostic-only labeling make those limitations visible rather than pretending to remove them.
