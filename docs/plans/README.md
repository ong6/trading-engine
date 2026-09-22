# Plans

One file per bounded piece of future work. A plan is the only way to admit work that is not a
backlog row or a reproduced defect (see `AGENTS.md`). Each plan has a YAML header with
`status` in `proposed | approved | active | done | dropped`; only the owner moves a plan to
`approved`. Agents may move `approved → active → done` and must record the transition in the
plan and the BUILDLOG.

| Plan | Status | One line | Owner decision needed |
|---|---|---|---|
| [P1 — Appliance mode](p1-appliance-mode.md) | active | Freeze growth, shrink the session loop, retire doc-pinning tests, put the box on a weekly check | None |
| [P2 — League collapse](p2-league-collapse.md) | approved | Retire 11 of 21 books whose question the evidence already answered | None |
| [P3 — Point-in-time data](p3-point-in-time-data.md) | approved | Sharadar recommended for survivorship-free research data; Norgate fallback | Set a spend ceiling before purchase |
| [P4 — Broker decision](p4-broker-decision.md) | done | Real broker eventually: IBKR primary, Moomoo fallback; P7 carries the simulator-only next step | None |
| [P5 — Agent paper decisions](p5-agent-paper-decisions.md) | done | Let a constrained agent control one isolated simulator-only paper book | None |
| [P6 — Alpha experiment](p6-alpha-experiment.md) | done | Run one theory-led fixed-instrument experiment under a frozen protocol | None |
| [P7 — Autonomous paper trial](p7-autonomous-paper-trial.md) | active | Compare algorithm-only, AI-only, and hybrid policies with a cloned S$10k envelope | Separate data-vendor budget remains unset |
| [P8 — Daily opportunity agent](p8-daily-opportunity-agent.md) | active | Detect daily standouts and retain bounded watch/hold/swing assessments and alerts | None |

Recommended order: P8's daily observation path and P7's monthly comparison may proceed without
sharing books or performance evidence; P1 and P2 remain admitted maintenance work, and P3 resumes
when the owner separately approves a data-vendor budget.

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
