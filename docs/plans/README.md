# Plans

One file per bounded piece of work. A plan is the way to admit work that is not a backlog row or a
reproduced defect (see [`AGENTS.md`](../../AGENTS.md)). Each plan has a YAML header with `status`
in `proposed | approved | active | done | dropped`; only the owner approves a plan. Agents move
`approved → active → done` and record the transition in the plan and the BUILDLOG.

This table is the single source of plan status for open plans; each plan's YAML `status` matches
its row. When a plan reaches `done` or `dropped`, move it to [`../history/plans/`](../history/plans/README.md)
and move its row to that index. Work order is [`../product.md`](../product.md) ("Focus now").

| Plan | Title | Status | Outcome |
|---|---|---|---|
| [P2](p2-league-collapse.md) | League collapse | approved | Retire paper books that answer no open research question; the active set is in `GET /meta` |
| [P3](p3-point-in-time-data.md) | Point-in-time data | approved | Free survivor-aware data first (Tiingo, Form 25, SEC bulk, Massive); paid data stays out |
| [P7](p7-autonomous-paper-trial.md) | Autonomous paper trial | active | Algorithm vs AI vs hybrid on one S$10k paper envelope; built, not activated |
| [P8](p8-daily-opportunity-agent.md) | Daily opportunity agent | active | Nightly standouts with watch/hold/swing assessments; its locked simulator tool has no active book |
| [P9](p9-multi-cadence-agent-tools.md) | Multi-cadence agent tools | active | Hourly and four-hour shadow observers beside the nightly simulator tool path |
| [P15](p15-profitability-evidence-loop.md) | Profitability evidence loop | active | Score every candidate against a deterministic baseline and paired comparator books; current revision in `GET /meta` |
| [P16](p16-challenger-lab-and-text-edge.md) | Challenger lab, text edge, evaluation science | active | Challenger lab, text labs and evaluation science; built and inert until W9b registration |
| [P17](p17-personal-host-ibkr-paper-execution.md) | Personal-host IBKR paper execution and reconciliation | proposed | Future work, not now: needs a Stage 1 pass and owner approval before any account action |
| [P22](p22-engine-v2-accounts.md) | Engine v2 accounts and money foundation | active | Engine v2 is the executor and ledger for paper accounts; open: the private alpha moves onto its engine-owned account |
| [P24](p24-quant-review-and-speed.md) | Senior-quant review, pipeline fixes, speed and new research lanes | active | Senior-quant review: pipeline fixes, output-identical speed work, new pre-registered studies |
| [P25](p25-ship-autodeploy-cleanup.md) | Ship continuously, clean the docs and code, keep the engine easy to extend | active | Continuous deploy, agent-first docs, short backup history and dead-code removal |

Finished plans (background only): [`../history/plans/`](../history/plans/README.md).

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

