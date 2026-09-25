---
plan: P13
title: Market-data source hardening
status: done
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
- Focused and full tests, Ruff, budgets, and service audit are green. An admitted-source live pass
  remains an explicit credential gate and cannot be replaced by a fixture or an unlicensed source.

## Budget

At most three commits, each below 1,500 inserted non-data lines. P13 may add at most 350 engine,
500 server, and 150 tools lines inside the existing repository ceilings; farm and sim do not grow.

## Risks

Unofficial protocols can change without notice, free feeds can be delayed or venue-limited, and
source-code licenses do not grant market-data rights. Provider failure must reduce evidence rather
than trigger fallback claims, silently blend feeds, or affect execution.

## Implemented state

_Superseded for TradingView by the 2026-09-25 activation below; the Alpaca gate still applies._

The provider registry, exact-response Alpaca IEX snapshot/history adapter, v3 hourly/four-hour prompt
cross-check, trace linkage, private environment-file hook, CLI status/capture entry point, and
fixture suite are implemented. TradingView is blocked before network access. This host has no
accepted Alpaca terms or credentials, so the new source correctly reports `unavailable`; existing
Yahoo evidence remains the only realtime input. Activation requires adding the following to
`~/.config/trading-engine/market-data.env` after accepting the applicable account/data terms:

```text
TRADING_ENGINE_ALPACA_DATA_TERMS_ACCEPTED=alpaca-market-data-terms-reviewed-2026-09-24
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
```

Create it with `install -m 600 /dev/null ~/.config/trading-engine/market-data.env`; it must be a
regular, owner-only file. Run `.venv/bin/python -m tools.market_data_source` to audit source admission and file
mode. Capture commands exit nonzero when unavailable, so a skipped live smoke cannot look successful.

The locally implementable portion is complete after three independent review/remediation cycles.
Activation of the optional Alpaca source remains gated on the provider agreement/credentials and a
real-response smoke test. The active v3 shadow policies start at 10:15/10:30 New York, require
closed fresh bars, and create no evaluation trace when those facts are unavailable.

## TradingView activation — 2026-09-25

The owner asserts the applicable non-display rights and authorizes anonymous TradingView quote and
chart access for internal automated research. P13 therefore adds exact WebSocket transcript capture,
realtime quote normalization, and bounded historical bar capture. Alpaca remains dormant. TradingView
data stays outside operational prices, fills, broker logic, and real-capital authority.

Implementation is complete: v4 shadow services query TradingView, exact sent/received WebSocket
transcripts are retained, fresh observations may enter prompts, and stale observations remain ledger-
only. A live AAPL capture retained a truthful stale overnight snapshot with no invented spread; a
bounded September 2022 capture retained 21 daily bars. Deployed hourly/four-hour services succeeded,
Alpaca remains dormant, and operational price/order/fill/position counts were unchanged.
