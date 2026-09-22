---
plan: P9
title: Multi-cadence agent experiments and paper tool calls
status: active
opened: 2026-09-22
owner_decision: approved 2026-09-22
---

## Goal

Compare hourly, four-hour, and nightly agent observations without multiplying execution risk. One
nightly policy may emit a typed paper-trade tool call; deterministic code locks, validates, records,
and converts it into a next-open simulator order. Intraday variants remain observation-only until
their independent evidence supports a later promotion decision. Add one algorithm-plus-agent lane
where the agent can veto, but never enlarge or rewrite, a deterministic candidate.

## Scope

1. Register versioned prompt/cadence variants with separate attempt and performance attribution.
2. Add one local `submit_paper_trade` schema for buy/sell intents. The model supplies symbol, side,
   thesis, invalidation, horizon, and evidence; code supplies quantity and every risk limit.
3. Serialize each decision window under an advisory lock, persist the request and response before
   consumption, and enforce one tool result/order per idempotency key.
4. Reuse P8's isolated book, candidate admission, news receipts, alert events, next-open simulator,
   and bounded status. No intraday bar may cause a same-bar fill.
5. Add a self-test covering malformed/duplicate tool calls, interruption replay, lock contention,
   cross-book isolation, risk rejection, and next-open execution.
6. Register, but do not tune or promote, one deterministic gap-and-volume candidate whose signal is
   the same P8 ranking input; compare algorithm-only, model-only, and veto-overlay outcomes on paired
   future windows.

## Not in scope

- Broker connectivity, credentials, live capital, unrestricted shell/network tools, arbitrary
  symbols, model quantities, leverage, shorting, options, same-bar fills, or retrying a model call
  after its output may have been observed.
- Giving all cadence variants order authority, pooling their results, or selecting a winning prompt
  before a frozen minimum sample.
- Adding another algorithm after seeing P8 outcomes; the gap-volume comparator is frozen from the
  already-defined P8 inputs before it begins prospective measurement.

## Done when

- Hourly and four-hour variants record observations under distinct identities and cannot reach an
  order writer; the nightly variant can create at most one attributed simulator intent per ticker.
- Every accepted tool call is durably recorded before an order, replays exactly without a second
  order or model call, and fills only through the ordinary later-session simulator step.
- The paired deterministic and veto-overlay paths share data/cost windows but retain separate books
  and attribution; status reports cadence, prompt, token, order, fill, and performance evidence.
- The self-test, full warnings-as-errors suite, static checks, backup/restore verification, and
  metrics budget pass before any timer with order authority is enabled.

## Budget

At most six commits, each below 1,500 inserted non-data lines. New non-test code is capped at 900
`server/` lines, 250 `engine/` lines, 150 `sim/` lines, and 150 `tools/` lines. Reuse P8 primitives.

## Risks

Multiple cadences can create correlated decisions, excess turnover, prompt selection bias, and
duplicate orders. Only one frozen nightly policy can write simulator intents; all other variants
are shadow observations. Separate attribution, one-call windows, locks, idempotency, deterministic
sizing, exposure caps, and paired forward evaluation prevent authority and evidence from pooling.
