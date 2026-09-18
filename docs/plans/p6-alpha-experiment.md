---
plan: P6
title: One theory-led deterministic alpha experiment
status: done
opened: 2026-09-18
owner_decision: approved 2026-09-18
---

Completed: 2026-09-18 with `REJECT-V1`; the frozen rule was not tuned or promoted.

## Goal

Run one new deterministic, economically motivated fixed-instrument experiment through a frozen
protocol that can honestly reject the hypothesis. It must compare net excess return with a proper
control, include realistic costs and delay stress, account for the single attempted variant, and
publish negative results unchanged.

## Scope

- Select one mechanism from fixed, liquid ETFs that is distinct from the rejected calendar rules.
- Write the charter and immutable machine-readable registration before computing results.
- Implement only the minimal experiment runner needed for that registration.
- Freeze instruments, availability rule, signal, rebalance cadence, control, costs, delay stress,
  primary statistic, minimum effect, sample rule, and kill criterion.
- Publish the full result, including rejection, without adding a league book or forward record.

## Not in scope

- Parameter grids, nearby variants, today's-stock-universe backtests, changing existing forward
  records, promoting a strategy, or interpreting standalone CAGR as alpha.

## Done when

The registration predates the result in Git history, the runner is deterministic and tested, and
the report states net excess versus its frozen control under baseline and delay/cost stress.

## Budget

Two commits and at most 900 new `farm/` lines, tests excluded. One registered variant only.

## Risks

The main risk is selecting the idea after looking at its result. The registration lands in the P5
commit before the P6 runner is executed, and a failed result closes the hypothesis without tuning.
