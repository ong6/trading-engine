# Plans

One file per bounded piece of future work. A plan is the only way to admit work that is not a
backlog row or a reproduced defect (see `AGENTS.md`). Each plan has a YAML header with
`status` in `proposed | approved | active | done | dropped`; only the owner moves a plan to
`approved`. Agents may move `approved → active → done` and must record the transition in the
plan and the BUILDLOG.

This table is the single source of plan status. `scope.md` links here instead of restating it;
each plan's YAML `status` must match its row.

| Plan | Title | Status | One-line outcome |
|---|---|---|---|
| [P1](p1-appliance-mode.md) | Appliance mode | active | Admitted maintenance; not progressed since approval (doc-pinning tests not yet retired) |
| [P2](p2-league-collapse.md) | League collapse | approved | Retire 11 of 21 books whose question the evidence already answered; not started |
| [P3](p3-point-in-time-data.md) | Point-in-time data | approved | Sharadar recommended, Norgate fallback; **blocked** until the owner sets a spend ceiling |
| [P4](p4-broker-decision.md) | Broker decision | done | Decided 2026-09-20: IBKR eventually (Moomoo fallback) on personal hardware, via a later execution plan |
| [P5](p5-agent-paper-decisions.md) | Agent paper decisions | done | Completed 2026-09-18: a constrained agent controls one isolated simulator-only book |
| [P6](p6-alpha-experiment.md) | Alpha experiment | done | Completed 2026-09-18: one frozen credit-confirmed SPY/BIL experiment |
| [P7](p7-autonomous-paper-trial.md) | Autonomous paper trial | active | Algorithm vs AI vs hybrid on a cloned S$10k envelope; built but **not yet activated** |
| [P8](p8-daily-opportunity-agent.md) | Daily opportunity agent | active | Live: nightly standouts, watch/hold/swing assessments, locked simulator trade tool |
| [P9](p9-multi-cadence-agent-tools.md) | Multi-cadence agent tools | active | Live: hourly and four-hour shadow observers plus the nightly simulator tool path |
| [P10](p10-2022-agent-replay.md) | 2022 agent replay | done | Contamination-labelled price-only diagnostic; cannot promote anything |
| [P11](p11-forward-agent-evaluation.md) | Forward agent evaluation | done | Evaluation ledger built; it operates as part of the appliance |
| [P12](p12-agent-research-product.md) | Agent research product | done | Full data, execution, and evaluation programme delivered 2026-09-23; data/news spend external |
| [P13](p13-market-data-source-hardening.md) | Market-data source hardening | done | TradingView realtime/history active under owner-asserted rights; Alpaca dormant |
| [P14](p14-tradingview-history-archive.md) | TradingView historical archive | done | Resumable current-liquid-universe daily bars with exact transcripts and research-only authority |

Recommended order: follow [`../direction.md`](../direction.md) ("Focus now"). P8/P9 run untouched
while P7 is activated; P1 and P2 remain admitted maintenance work; P3 waits for the owner's
data-vendor budget.

## Plan template

```
---
plan: P<n>
title: <short>
status: proposed
opened: YYYY-MM-DD
owner_decision: <what the owner must decide, or "none">
---

## Goal            one paragraph, what is true when this is done
## Why now         the evidence that makes this the next thing
## Scope           bullet list of the exact changes, with paths
## Not in scope    what an agent will be tempted to add, and must not
## Done when       a command and its expected output, or a metric threshold
## Budget          commits, lines, sessions
## Risks           what could go wrong and the rollback
```
