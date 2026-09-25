---
plan: P14
title: TradingView historical archive
status: active
opened: 2026-09-25
owner_decision: approved 2026-09-25
---

## Goal

Turn the bounded TradingView history capture into a durable daily-bar archive: freeze the current
liquid universe as an explicitly survivor-biased cohort, fetch it in resumable date chunks, retain
every exact transcript and bitemporal fact, and keep adding bounded work through the existing
single-writer queue.

## Why now

The live proof contains only 21 AAPL daily bars. The owner asked to retain historical data now so
future trading research has a growing local record. The source is admitted under the owner's
asserted non-display rights, but the current one-symbol command has no cohort, checkpoint, retry,
coverage, or unattended continuation contract.

## Scope

1. Freeze a cohort from `universe.active AND universe.liquid`, including canonical ticker, exact
   provider symbol, selection time, range, and current-universe selection warning.
2. Add append-only per-attempt results plus a resumable per-symbol/date checkpoint projection.
3. Fetch outside DuckDB locks; commit each successful bounded chunk through the existing exact-
   transcript and bitemporal-fact path; record empty ranges and failures without making bars.
4. Add one connection-narrowed `tradingview_history` queue kind and bounded nightly enqueue.
5. Expose a read-only JSON coverage/status projection and validate a small live canary before the
   unattended liquid-universe job is left pending.

## Not in scope

- Historical index membership, delisted securities, publication-time fundamentals/news, or a
  survivor-free backtest claim.
- Intraday history, redistribution, operational `prices`, fill pricing, execution authority, broker
  connectivity, credentials, or real capital.
- Unlimited parallel requests or retry storms. Missing data remains missing.

## Done when

- A killed/retried job resumes from explicit symbol/date checkpoints and successful replay is
  idempotent at the checkpoint boundary.
- Coverage distinguishes targets, attempted/successful/empty/failed chunks, facts, date span,
  pending work, and the current-universe survivorship limitation.
- A live canary retains exact transcripts and new daily facts without changing `prices`, orders,
  fills, or positions; queue, source, full tests, Ruff, budgets, and automation audit pass.

## Budget

At most two commits, each below 1,500 inserted non-data lines. Use no more than 650 existing spare
engine lines and 100 tools lines; server, farm, and sim do not grow. Repository ceilings do not
increase.

## Risks

TradingView's unofficial protocol may change or throttle a broad archive. Work is sequential,
bounded per run, backoff-controlled, and resumable. The current liquid cohort is useful for present
research but survivor-biased; its facts remain retrieval-time research evidence and cannot promote
a historical stock-selection strategy.
