---
plan: P11
title: Forward agent data and evaluation ledger
status: done
opened: 2026-09-23
owner_decision: approved 2026-09-23
---

## Goal

Create one point-in-time, append-only evaluation dataset for every active agent cadence so future
analysis can reproduce what the agent knew, what exact policy/model ran, what it decided, how an
intent executed, and what happened over frozen later horizons.

## Scope

- Record one canonical trace per decision window with policy/cadence/prompt/model/tool identities,
  event and availability times, information cutoff, input/output hashes and payloads, source
  references, latency, token usage, terminal status, and execution authority.
- Append delayed labels at frozen 1, 5, 10, and 20-session horizons: selected-asset/SPY returns,
  excess return, maximum adverse/favorable excursion, and exact label provenance.
- Integrate daily, hourly, and four-hour paths without changing their frozen decisions. Raw news
  responses and source-specific ledgers stay authoritative and are referenced rather than rewritten.
- Add completeness/freshness status and tests for duplicate windows, early labels, replay, identity
  loss, and cross-policy pooling.
- Publish a researched roadmap for point-in-time data, execution realism, and model evaluation.

## Not in scope

- Purchasing data, reconstructing unavailable history, model or policy tuning, new broker routes,
  real capital, or changing P8/P9 candidate and risk rules.
- Treating hourly bar simulation as order-book execution or exposing immature labels to policies.

## Done when

- Every new daily/hourly/four-hour terminal decision produces one replay-stable trace.
- Labels cannot be written before their horizon and reruns reproduce them without model calls.
- Status reports policy coverage and mature/unlabeled counts; full tests and budgets pass.

## Budget

At most four commits below 1,500 inserted non-data lines each; 650 server, 200 engine, 150 tools,
and 100 farm non-test lines.

## Risks

A second ledger can create conflicting truth. P11 stores immutable references and hashes, never
rewrites source evidence, and treats delayed labels as mechanical observations, not promotion gates.

## Status — 2026-09-24

Built and marked `done`: the evaluation ledger now operates as part of the appliance. The daily
opportunity service indexes each terminal decision and refreshes `data/reports/agent-evaluation.json`
after every run; `GET /agent/evaluation/status` reports coverage and maturity. Keeping it running is
maintenance under `../scope.md`, not further P11 work.
