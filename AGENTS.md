# Operating contract for agents

This repo is the **public, paper-only trading engine**: data collection, a point-in-time store, a
next-open fill simulator, paper books and accounts, evaluation statistics and the AI evidence loop,
with AI deciding inside deterministic controls. Strategies, prompts, parameters, registrations,
trial counts, findings and results go to the owner's **private alpha repo** (if unsure, treat a
change as alpha). Goal: [north star](docs/product.md#north-star). Live state: `GET /meta`,
`data/reports/`. Precedence: `docs/product.md` > this file > `docs/scope.md`. Each code folder's
`AGENTS.md` holds its entry points and local rules.

## Absolute rules

- Public repo: no employer, host or internal-tool names, absolute home paths or credentials in
  files or commit messages ("the host", `$HOME/…`). Commit dates are never rewritten.
- Never fabricate a price or bar. Point-in-time tables are append-only.
- Orders fill next-open, never same-bar. One DuckDB writer at a time; heavy work uses the queue.
- Every strategy and experiment is pre-registered with a kill criterion before evidence accrues.
- No broker code, broker credentials or real money on this host.
- Never weaken a gate to manufacture completion; never tune a frozen rule, registered value or
  threshold after seeing its outcome; never disturb producers or the E1, sector and XS records.
  Prove by running, not by reading.

## Admission test

A change other than a doc fix must match one of: a plan in `docs/plans/` with `status: approved`
or `active`, inside its scope; a reproduced defect (a failing test or command with wrong output,
recorded in the BUILDLOG entry; lint or a gap noticed while reading is not a defect); or a row of
the next-admissible-actions table in `docs/strategy-research-backlog.md` whose trigger fired.
Otherwise add one line under "Proposed, not approved" in `docs/scope.md` and stop; no side work.

## Decisions

The orchestrator owns technical decisions (design, placement, registered values, statistics,
acceptance, process); a worker blocked on one writes `blocked` with the question. The owner decides
product only: what to build, money and data purchases, broker accounts and capital, loss limits,
public presentation; ask in plain text. Apply owner corrections to the doc they govern, in present
tense. Workers stay within the orchestrator's daily budget, at most three concurrent writers.

## Session

1. `git pull --rebase origin main`; read your plan and the file the map names; check `GET /meta`.
2. Fast tier while working: `.venv/bin/python -m tools.affected_tests --run`; full suite once at
   the end: `.venv/bin/python -m pytest -q -W error -n 8`.
3. `python -m tools.metrics_snapshot --check-budget`, a BUILDLOG entry, commit; leave nothing
   uncommitted. Land with `python -m tools.land BRANCH --reason-file F --push` (or via the
   orchestrator). Merged to `main` with green CI is deployed by the deployer.

## Commits and BUILDLOG

Budgets (`docs/scope-budget.json`, enforced by `tests/test_operating_contract.py`, reported in
`data/reports/metrics/README.md`): one logical step per commit, under 1,500 inserted lines outside
`data/`; delete what a change makes dead; no new doc-pinning tests; no new endpoints, dashboards,
migrations, ledgers or operator CLIs without a plan. A BUILDLOG entry goes directly above the tail
marker, at most 25 lines and one SHA-256:

```
## YYYY-MM-DD — <one-line title>

- **Why:** the plan, admission row or reproduction that admitted this work.
- **What:** two to five lines of what changed, in plain words.
- **Evidence:** the one command that proves it and its salient output line.
- **Metrics:** LOC deltas from the snapshot, or "unchanged".
- **Next:** the single next step, or "nothing admitted" (never admits work).
```

## Map: doing X → read Y

| Doing | Read |
|---|---|
| Choose what to work on | `docs/product.md` (Focus now) |
| A scheduled run failed | `docs/operate/how-it-works.md` |
| Fix a data defect | `engine/AGENTS.md` |
| Add a strategy or experiment | `docs/extend/README.md` |
| Add a data source | `docs/data/README.md` |
| Change a pinned or registered file | `server/AGENTS.md` |
| Deploy or land a branch | `docs/change/deploy.md` |
| Run a backtest | `docs/change/backtest-standard.md` |
| Read today's evidence | `data/reports/README.md` |
| Write public docs | `docs/site/README.md` |
| Anything else | `docs/README.md` |
