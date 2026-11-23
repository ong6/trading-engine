# Add a strategy or experiment

Ideas move through one funnel: **register → screen on history → confirm on new data → paper
book**. "No edge" is the default answer, and every trial counts.

## Where the code goes

| You are adding | Repo | Where |
|---|---|---|
| Strategy logic, prompts, parameters, registrations, trial counts, results | private alpha repo | `registrations/`, `research/`, `strategies/`, `trials/`, `reports/`, `live/` |
| A reusable mechanic a strategy needs (order type, fill rule, statistic, panel, data source) | this repo | `sim/`, `farm/study/`, `engine/`; see the folder's `AGENTS.md` |
| A public demo strategy on the engine's league | this repo | `sim/strategies/` (pinned: needs a re-pin) |

If you are not sure whether something is infrastructure or alpha, treat it as alpha.

## 1. Register before any result exists

Write `registrations/<name>-<YYYY-MM-DD>.md` in the alpha repo. It must say:
- the hypothesis;
- the data rules and availability clocks;
- the variants and the controls;
- the primary cost profile and one harsher one;
- the comparator;
- the pass bar and the kill rule;
- the sealed holdout.

Add its trials to the census in `trials/`, which raises N. After that, the registration is
frozen: a changed idea is a new registration with new trials.

## 2. Screen on history

Build the study on the shared backtest core (`farm.study`). It supplies point-in-time panels,
named costs, benchmarks, statistics, holdouts and reports.
- Start from `farm/study/examples/spy_trend.py`.
- Meet the checklist in [`../change/backtest-standard.md`](../change/backtest-standard.md).
- Read the operational store only through the published snapshot
  (`store/snapshots/market-latest.duckdb`), read-only.

The run gives **PASS**, **ADMIT** or **KILL** under the program's bars. The report goes to
`reports/`.

## 3. Confirm on new data

A PASS or ADMIT candidate gets a confirmation registration that freezes its code commit, prompts,
model identity, data and accounting rules. It is then judged only on events after that freeze.
- The runner lives in `research/` and its timer in `systemd/` (alpha repo).
- The runner appends to a ledger.
- It decides once, at the registered horizon and trade count.

## 4. Paper book

A confirmed candidate runs as a paper book in the alpha repo, in the same shape as
`live/t4_forward.py`:
- immutable decisions, published before the fill;
- fills from the published snapshot;
- an append-only ledger;
- `systemd/<name>-signal` and `-settle` timers;
- no broker, ever.

Engine-hosted books for private strategies are not built yet; that is the plug-in boundary
parked in [`../scope.md`](../scope.md). Moving to money follows the stages in
[`../product.md`](../product.md), and every step that touches money is the owner's call.

## Rules that bite

- Never tune a frozen rule after seeing its outcome. Never weaken a gate to get a pass.
- One DuckDB writer: alpha code never writes `store/market.duckdb`.
- Orders fill next-open; prices are never invented.
- Data stays free ([`../data/README.md`](../data/README.md)).
- Changing a pinned engine file needs a re-pin:
  1. `python -m tools.repin --check`;
  2. land it with `python -m tools.land BRANCH --push`.
  The deployer ships it ([`../change/deploy.md`](../change/deploy.md)).
- This repo is public: no strategy specifics, results, employer or host names.
