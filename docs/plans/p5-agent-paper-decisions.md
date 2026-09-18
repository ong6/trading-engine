---
plan: P5
title: Capital-disabled agent paper decisions
status: done
opened: 2026-09-18
owner_decision: approved 2026-09-18
---

Completed: 2026-09-18 after two rounds of independent safety review and remediation.

## Goal

One constrained agent-only policy can turn its retained, deterministically validated decision into
an idempotent next-session order in its own simulator portfolio. The model chooses proposal versus
no action; deterministic code owns validation, sizing ceilings, risk, persistence, and fills. No
broker adapter, credential, network submission, live toggle, or real capital is reachable.

## Scope

- Add one application service under `server/` that reconstructs a completed decision window from
  retained evidence and atomically records either no action or one pending simulator order.
- Require an initialized isolated agent-only portfolio, exact policy/context/proposal identities,
  a valid future signal date, a fresh accepted proposal, available cash or position, and the
  existing deterministic notional ceiling.
- Add an authenticated-local operator route or bounded runner entrypoint for one decision window.
- Persist an append-only decision-consumption receipt and expose its result through existing agent
  read models. Duplicate consumption returns the original result and cannot duplicate an order.
- Test proposal, no-action, rejection, duplicate, rollback, portfolio separation, and absence of
  broker/live authority.

## Not in scope

- Broker-paper or live-broker submission, credentials, real capital, shorting, leverage, options,
  arbitrary symbols, self-approval, model-written risk limits, or changes to frozen strategies.
- Automatic-paper authority leases or the generic future broker-consumption bridge.

## Done when

Focused tests prove one accepted decision produces at most one next-session simulator order in the
reserved book, model no-action produces none, every drift fails closed, and broker-boundary tests
remain green. The full warnings-as-errors suite passes.

## Budget

Two commits, at most 900 new `server/` lines and 200 new `tools/` lines, tests excluded.

## Risks

The main risk is accidentally reusing broker authority machinery. The implementation writes only
the existing simulator order ledger and a dedicated receipt; structural tests reject broker calls.
