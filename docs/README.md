# Documentation index

Agents start at [`../AGENTS.md`](../AGENTS.md). Docs state current rules and structure; anything
that changes (books, revisions, live producers, counts) comes from `GET /meta` and the generated
reports under [`../data/reports/`](../data/reports/README.md). Every top-level directory has a short
`README.md` with its entry points.

## Decide what to work on

- [`product.md`](product.md) — north star, what "makes money" means, decisions, focus order.
- [`scope.md`](scope.md) — what runs, what is frozen and why, the "proposed, not approved" list.
- [`plans/README.md`](plans/README.md) — open plans and their status.
- [`strategy-research-backlog.md`](strategy-research-backlog.md) — the deterministic research
  queue and its [next admissible actions](strategy-research-backlog.md#next-admissible-actions).
- [`feedback.md`](feedback.md) — the owner verdict ledger.

## Operate

- [`operate/how-it-works.md`](operate/how-it-works.md) — runbook: first response, schedules,
  watchdog, snapshots, API and UI, recovery.
- [`settlement-runbook.md`](settlement-runbook.md) — dead and delisted positions (stays at this
  path because the provider contract scans `docs/*runbook*.md`).
- [`metrics.md`](metrics.md) — what the drift snapshot measures.

## Change

- [`change/testing.md`](change/testing.md) — fast tier, full suite, lint, doc-test rules.
- [`change/deploy.md`](change/deploy.md) — how merged `main` reaches the host.
- [`change/backtest-standard.md`](change/backtest-standard.md) — requirements for historical studies.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — contribution rules and tool details for humans.
- `scope-budget.json` — hygiene budgets enforced by `tests/test_operating_contract.py`.

## Extend

- [`extend/README.md`](extend/README.md) — adding a strategy or experiment.
- [`charters/`](charters/) — frozen research charters: [credit-confirmed trend](charters/credit_confirmed_equity_trend.md),
  [EW drawdown throttle](charters/ew_dd_throttle.md), [EW gross vol target](charters/ew_gross_voltarget.md),
  [EW sector capped](charters/ew_sector_capped.md), [fixed-ETF rebalancing](charters/fixed_etf_rebalancing_premium.md),
  [multi-asset trend](charters/multi_asset_trend.md), [sell in May](charters/sell_in_may_spy.md),
  [turn of month](charters/turn_of_month_spy.md), [VIX term](charters/vix_term_spy_timing.md),
  [XS momentum 12-1](charters/xs_momentum_12_1.md), [XS reversal 1m](charters/xs_reversal_1m.md).

## Architecture

- [`architecture/system-blueprint.md`](architecture/system-blueprint.md) — what is being built,
  where an edge could come from, the research funnel.
- [`architecture/architecture-reference.md`](architecture/architecture-reference.md) — components,
  data flow, league, agents, API and authority boundaries.
- [`architecture/paper-account-contract.md`](architecture/paper-account-contract.md) — engine-owned
  paper accounts and the accounting invariants.
- [`architecture/glossary.md`](architecture/glossary.md) — plan codes and research terms.
- [`architecture/product-agent-research-platform.md`](architecture/product-agent-research-platform.md) — agent research platform requirements.
- Design specs: [engine design](architecture/design/trading-engine-design.md) (§12 wins on
  conflict), [execution design](architecture/design/trading-execution-design.md),
  [paper-authority state machine](architecture/design/paper-authority-state-machine.md),
  [Stage 2 broker paper](architecture/design/stage2-broker-paper.md) (design only),
  [prompt review](architecture/design/prompt-review.md).

## Data

- [`data/README.md`](data/README.md) — stores, the dataset catalogue, data rules.

## Public site

- [`site/README.md`](site/README.md) — plain-language product pages, starting at
  [`site/index.md`](site/index.md).

## Background

- [`history/README.md`](history/README.md) — archive of dated audits, finished plans, old BUILDLOG
  entries and superseded rules. Background only; never current.
