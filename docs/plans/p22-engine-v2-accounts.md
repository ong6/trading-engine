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
  Frozen runtime hashes and P15 revision 13 deliberately remain for Phase B.

### L3 Phase B — only after the orchestrator's merge signal

- Merge the refreshed shared base containing L1, L2, L4 and the final R13 schema API; remove the
  temporary compatibility shim.
- Explicitly revise the E1, sector, XS and walk-forward runtime contracts, then issue P15
  registration revision 13 with unchanged scoring, labels, gates and schedules.
- On a snapshot copy, apply the migration and rerun the final pre-D0 session; require
  `league.csv` to remain byte-identical. Re-enable `tests/test_p15_registration.py` and require
  the full suite to pass before deployment.

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
supported-timezone suites and revision 13 pass, a store-copy rehearsal keeps pre-D0 reports
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
