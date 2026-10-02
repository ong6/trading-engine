# Backtest standard

Every historical study must make the same claims on the same measurement basis. The shared core
under `farm.study` supplies that basis; a study supplies only its frozen data declaration,
strategy specification, parameters, windows, cost choices, benchmark, census N, and output paths.
This checklist governs historical screening evidence. It does not turn a backtest into prospective
evidence or grant simulator or broker authority.

## Required study declaration

Before the first run, freeze:

- the data source and snapshot hash, each field's availability rule, market calendar, listing
  history coverage, survivor status, and any declared publication lag; when supplied, the
  independent secondary price source has its own declaration and snapshot hash; study-private
  derived inputs and cash-dividend rows declare their schema and gate every row by an availability
  timestamp;
- the strategy kind, pure decision function source, canonical parameters, decision time, fill
  point, exit or rebalance rule, notional/capital basis, order priority and signal fields,
  already-held rule, dividend withholding, `window_end` treatment, whether a complete held-price
  path is required, universe, and liquidity rule;
- one primary named cost profile and at least one distinct harsher sensitivity;
- one benchmark and whether it is the normal gross comparator or the explicitly labelled
  cost-bearing `allocation` mode;
- at least six yearly development folds after the burn-in, one sealed holdout, the one-shot marker
  path, and the all-study trial-census N used by DSR;
- the stationary-bootstrap seed, draw count and mean block length, plus the required output paths;
- the expected runtime and worker count on named generic hardware (CPU count is enough; do not put
  hostnames in a public artifact).

The resulting run identity is the SHA-256 of the exact strategy source, canonical parameters, core
version, selected cost-profile hashes, and data-snapshot hash. It appears in Markdown, JSON, and
the study-owned census row. A refactor may claim equivalent evaluation only when the frozen input
and output bytes, including that identity or a documented core-version transition, pass the
study's identity check.

## Checklist and core mapping

| Requirement | What a conforming study proves | Shared core |
|---|---|---|
| Declared data | Source, snapshot, point-in-time status, availability lags and calendar are explicit. A view cannot read beyond its decision timestamp or hard maximum date. | `farm.study.data` |
| Survivor status | Listing intervals determine eligibility when supplied. A current-listings-only source prints `SURVIVOR-BIASED SOURCE`; delist exits and fallback-return uses are counted. | `farm.study.universe`, report data section |
| Named costs | The primary and a harsher sensitivity are versioned and hashed. Fractional shares, per-side fees, funding and liquidity tiers are applied exactly. Unverified profiles are caveats. | `farm.study.costs` |
| Benchmark rule | The benchmark covers the identical sessions. Primary excess is strategy net minus benchmark gross; absolute net above zero is a separate required check. An `ew_eligible` comparator resolves its declared input at the trade decision time. Cost-bearing comparison exists only as labelled `allocation` mode. | `farm.study.benchmark` |
| Shared statistics | Trade mean, entry-session-clustered SE and one-sided t; full calendar-session returns including inactive zeros; annualised Sharpe; DSR with required census N; folds, recency, stationary-bootstrap CI, drawdown, worst month, exposure, turnover and capacity. | `farm.study.stats` |
| Development and holdout | At least six yearly post-burn-in folds. Development cannot load holdout rows. The holdout marker is created atomically once, before access, and cannot be reused. | `farm.study.protocol` |
| Fill realism | Declared fill follows the information time, never uses an unavailable bar, and handles missing/delisted names explicitly. For small or illiquid names, compare sampled fills with an independently declared price source; report trade-day coverage, signed fill-field differences, a secondary-price trade result and uncovered trades. Report notional/MDV60 and notional/auction-volume capacity. | `farm.study.data`, `farm.study.run`, cross-check and capacity report fields |
| Native simulation | Event orders and portfolio target weights use the same point-in-time views, fill points, costs, dividends, benchmark windows and deterministic runner. Conditional exits evaluate a pure predicate from the registered first-check session and use their declared maximum-session fallback. | `farm.study.simulate` |
| Proven evaluator | Unit tests cover exact formulas and failure paths; refactors have an identity check; seeded known-answer tests cover power, size, look-ahead, survivorship, costs and benchmark arithmetic. | `tests/test_study_*.py`, `farm.study.synthetic` |
| Stated runtime | Report wall time, worker count, job count, platform-neutral CPU count, and whether serial/parallel bytes match. | `farm.study.run`, report identity section |

## Interpretation rules

An inactive event session contributes zero to the calendar return series; it is not removed. Event
capital is `maximum concurrent slots × slot notional`, so trading rarely cannot inflate Sharpe or
DSR by changing the denominator or clock. Portfolio returns use the declared capital base and
complete rebalance path. Report both strategy net return and `strategy net − benchmark gross`;
neither substitutes for the other.

The ordinary comparator never pays transaction costs. If a question is specifically about two
allocation implementations with matched turnover, select `mode="allocation"`; the report must say
that both sides pay their own declared costs and must not mix that number with ordinary excess.

An official open used as an `at_open` decision input is an approximation for a pre-market
indication, permitted only with `open_as_indication=True`. The exact phrase
`open_as_indication` then appears in caveats. A close, high, low, volume, later intraday bar, future
membership row, or holdout row requested too early raises `LookAheadError`.

A conditional exit that decides from its session's official close requires
`close_as_indication=True`, and the report carries that exact caveat. Native event ledgers have a
stable schema: entry/exit session and field, ticker, side, prices, fractional shares, notional,
entry/exit/funding costs, dividend cash and net return by profile, primary
gross/net/benchmark/excess returns, exit reason, and flags. Entry-notional exit costing is a
reported registered approximation; market value remains the default. Portfolio ledgers record
every calendar session's NAV, return, benchmark, gross exposure, turnover, dividend cash,
per-profile costs and missing-data flags; flat sessions remain zero.

Every event study declares `window_end="force_close"` or `"unevaluable"` and explicitly declares
`require_complete_path`. Under `unevaluable`, a conditional fallback or fixed exit beyond the run
window is excluded and counted, without reading beyond the window. With a required complete path,
any missing or invalid held-session bar likewise excludes and counts the trade. The compatibility
defaults are forced window-end handling and no complete-path requirement.

A cash dividend belongs to a position held at the ex-date open and is credited through an exit on
or after that open. Strategy and equal-weight benchmark returns use the same withholding rate;
reports retain gross-of-withholding and net cash. An entry at the ex-date open does not qualify.

If a held name delists, use its last available close when one exists. If no exit price exists,
apply the predeclared delisting return (default −30%) and count it. Never delete the name from
history, carry an invented quote, or substitute today's membership. A source without historical
delisted names is still usable for diagnosis only when the survivor warning is prominent.

## Required report shape

Every Markdown and JSON report has these sections in this order:

1. data declaration: source, snapshot, point-in-time status, lags, and survivor status;
2. primary cost and every sensitivity, including hashes and verification flags;
3. benchmark kind, ticker/universe if applicable, gross or `allocation` mode;
4. independent-price cross-check: trade-day coverage; signed `primary / secondary - 1` mean,
   median, p5, p95 and share beyond 0.5% for each fill field; result recomputed only from covered
   secondary prices; and uncovered trade count, with no primary-price fallback;
5. per-variant results with absolute-net and excess checks;
6. all development folds and the last-three-fold recency view;
7. holdout, only if the one-shot marker was opened;
8. generated caveats, including open indication, survivor bias, unverified costs, and fewer than
   100 trades;
9. one plain-English conclusion per variant, plus runtime and run identity.

Missing evidence is `unavailable` or `insufficient`, never zero. JSON is the canonical machine
artifact; Markdown renders the same values. Both are written atomically and deterministically.

## Minimum proof commands

Run the focused suite, then the repository gates once at the checkpoint:

```sh
.venv/bin/python -m pytest -q -W error tests/test_study_*.py
.venv/bin/python -m pytest -q -W error -n auto
.venv/bin/ruff check .
.venv/bin/python -m tools.metrics_snapshot --check-budget
```

The synthetic proof reports its 50-seed power rate, planted-effect error in standard errors,
200-seed null rejection count and exact 99% binomial band, all four canaries, and the
serial/parallel byte comparison. A real-data example is run only against an explicit read-only
copy created by `tools.backup_database create`, outside production windows, and that copy is
deleted after use. Generated study reports and censuses stay with the study and are not committed
under `data/`.
