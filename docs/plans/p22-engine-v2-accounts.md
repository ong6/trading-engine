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
account risk, and deterministic account results.

## Why now

The owner chose the engine as the sole executor and ledger for versioned alpha accounts. Every
fill must carry costs from an effective-dated profile, while old zero-fee books must replay
exactly until an explicit migration break.

## Scope

- Additive schema, monotonic order ids, instrument identities, order lifecycle, costs, and ledger.
- Auction, intraday, short, margin, account service, risk, and deterministic result layers.
- Explicit migration break, public/private report separation, account reconciliation, and data
  capture needed by the generic engine contract.
- Integration rehearsal, registered source revision, and deployment gates owned by the later
  plan lanes.

## Not in scope

No private strategy name, prompt, parameter, registration, evidence, or result. No broker
connection, credential, real money, options execution without quote data, or retroactive change
to a frozen pre-break book.

## How to run this plan

Run the separately claimed lanes in dependency order, with one writer per clone. Each lane uses
temporary databases, commits its bounded logical steps, and publishes focused and full-suite
evidence. The orchestrator merges, rehearses, revises registered identities, and deploys only
after every lane is accepted.

## Done when

All lane acceptance tests and both supported-timezone suites pass; a store-copy rehearsal keeps
pre-break reports byte-identical; account replay reproduces positions and cash; migration is
one-shot; private accounts stay out of public reports; and deployment checks show deterministic
orders, fills, fees, cash events, equity, halts, and reconciliation.

## Budget

One commit per logical step under 1,500 inserted non-data lines. Lane file claims are exclusive;
the integration lane owns cross-lane documentation and registration closure.

## Risks

Legacy positional inserts must retain their table shapes, effective dates must select the exact
fee rule, and replay phase ordering must match live accounting. Any mismatch blocks deployment;
rollback restores the pre-migration database backup and source revision.
