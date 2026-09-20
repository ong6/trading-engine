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
| [P4 — Broker decision](p4-broker-decision.md) | active | Real broker eventually: IBKR primary, Moomoo fallback; implementation still frozen | None |
| [P5 — Agent paper decisions](p5-agent-paper-decisions.md) | done | Let a constrained agent control one isolated simulator-only paper book | None |
| [P6 — Alpha experiment](p6-alpha-experiment.md) | done | Run one theory-led fixed-instrument experiment under a frozen protocol | None |

Recommended order: P1 now, P2 the following week, P3 when the owner has picked a vendor, P4
by its date or earlier.

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
