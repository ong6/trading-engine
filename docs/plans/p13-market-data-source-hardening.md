---
plan: P13
title: Market-data source hardening
status: active
opened: 2026-09-24
owner_decision: approved 2026-09-24
---

## Goal

Add a provider-neutral boundary for exact-response realtime quotes and historical bars, admit one
official API source when its account credentials and terms permit automated research, and prevent
unlicensed data from silently entering agent decisions or trading state.

## Scope

1. Record source identity, entitlement, use class, freshness, raw response bytes, normalized facts,
   and explicit execution/historical authority for every new provider observation.
2. Add an optional official-API adapter for bounded realtime quote cross-checks and isolated
   historical capture. Missing credentials or malformed/stale responses fail to unavailable.
3. Expose admitted cross-check evidence to hourly/four-hour prompts without replacing the exact
   Yahoo five-minute bars or granting execution-price authority.
4. Register TradingView as blocked for automated non-display use unless a separate written data
   agreement is accepted; retain no live TradingView payload from evaluation probes.
5. Test fixtures, exact receipt linkage, timestamp/price validation, source fallback, and one live
   smoke request when credentials are present. Audit tonight's agent services afterward.

## Not in scope

- Circumventing TradingView terms, session controls, exchange entitlements, or rate limits.
- Treating IEX-only or delayed quotes as a consolidated feed, filling historical PIT gaps with
  retrieval-time data, or overwriting operational prices.
- Broker connections, order routing, real capital, new strategies, or increased agent authority.

## Done when

- Every configured source has an explicit admitted/blocked state and permitted-use contract.
- Realtime and historical responses are exact-byte retained and normalized only after validation.
- Agent prompts identify source, venue, timestamp, freshness, and research-only authority.
- TradingView cannot be selected without an explicit non-display agreement gate.
- Focused and full tests, Ruff, budgets, service audit, and an admitted-source pass are green.

## Budget

At most three commits, each below 1,500 inserted non-data lines. P13 may add at most 350 engine,
250 server, and 150 tools lines inside the existing repository ceilings; farm and sim do not grow.

## Risks

Unofficial protocols can change without notice, free feeds can be delayed or venue-limited, and
source-code licenses do not grant market-data rights. Provider failure must reduce evidence rather
than trigger fallback claims, silently blend feeds, or affect execution.
