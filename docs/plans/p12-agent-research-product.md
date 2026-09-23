---
plan: P12
title: Agent research product programme
status: done
opened: 2026-09-23
owner_decision: approved 2026-09-23
---

## Goal

Deliver the product described in the agent-research PRD: bitemporal evidence, raw intraday source
receipts, reproducible forward and historical agent datasets, horizon/invalidation exits, execution
latency and shortfall, paired policy scoring, contamination diagnostics, and vendor-neutral PIT data
adapters, while retaining simulator-only authority.

## Scope

1. Product and data contracts: canonical PRD, bitemporal fact envelope, stable source/entity IDs,
   immutable revisions, completeness checks, and raw intraday quote receipts.
2. Execution lifecycle: deterministic maximum-hold and machine-readable invalidation exits; complete
   decision/tool/order/fill/cost/position/equity latency and shortfall attribution.
3. Evaluation: complete P11, paired window/control metrics, calibration and forecast error, missing-
   window accounting, prompt/cadence comparison, and contamination probes.
4. Historical data: vendor-neutral manifests/import validators and SEC EDGAR acceptance-time forward
   capture. Paid Sharadar/Norgate/news download remains gated on budget and accepted license.
5. Operations: one bounded status/report surface, self-tests, backup/restore rehearsal, and frozen
   cohort activation checks.

## Not in scope

- Buying subscriptions without an approved spend ceiling, scraping around licenses, connecting a
  broker, using real capital, increasing leverage/shorting/options authority, or tuning P8/P9 from
  early outcomes.
- Treating bar data as order-book execution or model historical replay as promotion evidence.

## Done when

- Every feature in the PRD is implemented or has an explicit external gate with an acceptance test.
- Native agent decisions are bitemporal, reproducible, execution-linked, and maturity-labeled.
- Simulator exits and execution-quality metrics are deterministic and tested end to end.
- Full tests, static checks, recovery rehearsal, service audit, and source budgets are green.

## Budget

At most twelve reviewable commits, each under 1,500 inserted non-data lines. New non-test code is
capped at 900 server, 500 engine, 350 tools, 250 farm, and 150 sim lines.

## Risks

The programme can become infrastructure-heavy without better research. Each phase must produce a
queryable dataset, measurable decision/execution metric, or verified external gate. No phase may
create a new strategy merely to exercise infrastructure.

## Completion — 2026-09-23

Every locally implementable requirement is shipped and verified. The final prospective ledger has
6 native traces and 22 decisions; all 88 horizon outcomes are honestly immature at activation. The
deterministic research fleet has one current 18/18 walk-forward cohort, the three agent cadence
timers are enabled, the locked simulator self-test passes with no broker route, and a final 57-table
recovery bundle verifies independently. Paid PIT acquisition, SEC activation, intraday authority,
and broker/real-capital operation remain explicit external gates rather than simulated completion.
