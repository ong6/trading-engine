---
plan: P22
title: Engine v2 accounts and money foundation
status: active
opened: 2026-10-06
owner_decision: approved by the owner's engine and account decisions of 2026-10-06
---

## Goal

Build the generic public execution and accounting foundation for independently funded paper
accounts: stable instrument and order identities, versioned costs, side-aware positions, replay,
account risk, and deterministic account results. The engine is the sole executor and ledger;
private alpha owns versioned trade decisions and consumes receipts and results.

## Why now

The owner chose the engine as the sole executor and ledger for versioned alpha accounts. Every
fill must carry costs from an effective-dated profile, while old zero-fee books must replay
exactly until an explicit migration break.

## Locked decisions

- One account per alpha version; a passed backtest creates a new side-by-side version rather
  than mutating a live one.
- Every book pays `ibkr_pro_tiered_v1` from parameterized D0. The migration records a break and
  restarts book-comparison clocks without changing pre-break evidence or the P15 primary IC test.
- Generic paper accounts support next-open, MOO, MOC and deferred intraday fills, explicit
  stock short/cover sides, margin and the account-selected day-trade rule.
- Halts fire at −20% peak drawdown, −5% daily loss or reconciliation mismatch. Positions remain
  held and marked. Monthly review is a kill check only.
- Options reference and daily-bar capture is admitted; execution is refused until bid/ask data
  exists. No broker connection, credential or real capital is admitted.

## Account settings and compatibility

The positional `portfolios` schema remains unchanged. Engine route, cost profile, account type,
visibility, status, price source, day-trade rule and short permission live in
`portfolio_accounts` and are read through `sim.schema.portfolio_account` /
`portfolio_accounts_v`, then written only through `set_portfolio_account`. Legacy rows without a
side-table record receive the documented defaults. Every `sim_orders` writer allocates through
the monotonic sequence helper.

## Scope

- Additive schema, monotonic order ids, instrument identities, order lifecycle, costs, and ledger.
- Auction, intraday, short, margin, account service, risk, and deterministic result layers.
- Explicit migration break, public/private report separation, account reconciliation, and data
  capture needed by the generic engine contract.
- Integration rehearsal, registered source revision, and deployment gates owned by the later
  plan lanes.

### L3 Phase A

- Route league, P15, P16 and account portfolios to their owning fill engines; insert lazy
  accrual, account-settlement and halt phases in the nightly transaction.
- Charge league/P8/P15/P16 fills through the shared cost registry and ledger from their recorded
  break, protect every attributed order on rerun, and publish only public portfolios.
- Add the one-shot `--d0` migration, break-aware report columns, first-fetch backfill hook and
  restarted sector, XS, P15-book and P8 review clocks.
- Record the owner decisions and this architecture in the product, scope and blueprint docs.
  Phase B explicitly revises every frozen runtime and P15 registration only after integration.

The reviewed Phase A branch has merged the refreshed L0/L4 base and now uses the final R13 API
directly; no compatibility shim remains.

### L3 Phase B — only after the orchestrator's merge signal

- Merge the refreshed shared base containing the accepted L1 and L2 account execution/money
  layers while retaining the final R13 schema API.
- Explicitly revise the E1, sector, XS and walk-forward runtime contracts, then issue P15
  registration revision 14 on top of revision 13 with unchanged scoring, labels, gates and schedules.
- On a snapshot copy, apply the migration and rerun the final pre-D0 session; require
  `league.csv` to remain byte-identical. Re-enable `tests/test_p15_registration.py` and require
  the full suite to pass before deployment.

Phase B source integration and explicit runtime/P15 revision 14 binding are complete; the
both-timezone suites and full account/migration rehearsal remain the final acceptance gates.

## Not in scope

No private strategy name, prompt, parameter, registration, evidence, or result. No broker
connection, credential, real money, options execution without quote data, or retroactive change
to a frozen pre-break book.

## How to run this plan

Run the separately claimed lanes in dependency order, with one writer per clone. Each lane uses
temporary databases, commits its bounded logical steps, and publishes focused and full-suite
evidence. The orchestrator merges, rehearses, revises registered identities, and deploys only
after every lane is accepted. L3 stops after Phase A status and resumes only on the explicit
orchestrator signal for Phase B.

## Done when

Phase A is done when its focused routing, rerun, fee, break, migration, clock and driver tests
pass; Ruff is clean; and the full suite adds no failure outside the recorded frozen-identity
baseline while P15 registration remains deselected. The complete plan is done only when both
supported-timezone suites and revision 14 pass, a store-copy rehearsal keeps pre-D0 reports
byte-identical, account replay reproduces positions and cash, migration is one-shot, private
accounts stay out of public reports, and deployment checks show deterministic orders, fills,
fees, cash events, equity, halts, and reconciliation.

## Budget

One commit per logical step under 1,500 inserted non-data lines. Lane file claims are exclusive;
the integration lane owns cross-lane documentation and registration closure.

## Risks

Legacy positional inserts must retain their table shapes, sequence allocation must remain above
every legacy id, effective dates must select the exact fee rule, and replay phase ordering must
match live accounting. The nightly account-freshness read is fail-soft; settlement and ledger
failures are not. Any migration, replay, privacy, rehearsal or frozen-identity mismatch blocks
deployment; rollback restores the pre-migration database backup and source revision.

## Progress

- L0–L4 accepted and integrated; the private-alpha lane (L5) is accepted against the account
  contract and its merge is held for the post-deploy cutover.
- Integration (PR #13, `p22/lifecycle`) completed 2026-10-08; lifecycle review rounds 2–6
  followed. On 2026-10-15 the orchestrator accepted round 6 (`42083c4`: CI green in both
  timezones, 4,728 tests) and the owner accepted engine v2.
- 2026-10-15: `origin/main` (P23 hourly digest at :08 UTC, walk-forward invalid reasons,
  agent-shadow connect window) merged into `p22/lifecycle`. No revision-14 registered file
  changed.
- Admitted before deployment (owner, 2026-10-15), each with a reproduction first:
  single-attempt writer opens use the default lock-retry window; walk-forward drops a fold
  with fewer than two training sessions and says so; the TradingView archive retries an
  exhausted window after a cool-down; the nightly league mark no longer publishes P15 equity
  before that session's P15 fills; the P15 price-fetch record covers only names it can fetch;
  a split-like re-fetch triggers the action fetch and back-adjustment; phantom bars with a
  non-positive open, high or low are not real bars; the weekly full price verify keeps its
  own result and the nightly check says when the newest session was not checked; the weekly
  walk-forward data commit is titled as such; the ops digest trusts the systemd result for a
  clean stop; a delisted holding is closed out at its last real traded close.
- Remaining gates: re-pin revision 14 and the frozen runtime contracts once after the last
  fix, both timezone suites, the store-copy rehearsal on the final source, then deployment on
  Sunday 2026-10-18 19:00–23:00 UTC with D0 2026-10-19 (`P22_APPROVED_SHA` is that final
  source).
