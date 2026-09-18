# Charter — `xs_momentum_12_1`

_Pre-registration, 2026-09-02. **League book** (registered in
`sim/strategies/configs.py`; `sim.league --init` creates its `portfolios` row at the
next nightly, and its first monthly signal is the last session of 2026-09)._

Status: **book — the control** · Class: `sim/strategies/xs_momentum_12_1.py`
(shared scan in `sim/strategies/xs_common.py`) · Cadence: **monthly**, matching
`ew_benchmark` so the spread is attributable to selection and not to trading frequency.

## Hypothesis

Every comparison in this store is "vs `ew_benchmark`", and `ew_benchmark` *is* the
Minervini trend-template screen: the top 50 passers by RS, equal weight, monthly.
"The screen is the edge" (`docs/evaluation-2026-09-02.md` §2) is therefore the
untested assumption underneath every other result. The template is a dressed-up
momentum filter — RS rank, price above rising 150/200-day averages, within 25% of
the 52-week high — so the null hypothesis is:

> **H0.** The screen's return is plain cross-sectional momentum. A book that ranks the
> same liquid universe by trailing 12-month return, skips the last month, and holds the
> top 50 equal-weight is INDISTINGUISHABLE from `ew_benchmark` on median excess return
> and worst-fold drawdown.

The alternative, which the store has implicitly assumed since July, is that the
template's trend-structure conditions add value *beyond* the momentum rank.

## Mechanism (what the book does, exactly)

1. Universe: `universe.active AND liquid AND NOT etf`, close ≥ $5, at least 253 stored
   sessions. No screen, no fundamentals, no RS rank.
2. Signal: total return (price + dividends going ex in the window) from the close 252
   sessions ago to the close 21 sessions ago — Jegadeesh–Titman 12-1. The most recent
   month is skipped because the one-month effect is a *reversal* (see `xs_reversal_1m`)
   and would contaminate the rank.
3. Selection: top 50 by that return. Equal weight 1/50. Monthly at the last session of
   the month, filled at the next open through the standard fill model.
4. **No banding, no stops, no regime gate.** A held name that falls out of the top 50 is
   sold. This is deliberate: banding is a rule, and the control tests no rules.

Design decisions and why:

| Choice | Value | Reason |
|---|---|---|
| `n` | 50 | Matches `ew_benchmark`'s `cap`, so the book is EW's basket size with a different ranking and nothing else differs. Top *decile* of ~2.9k names would be ~290 slots of $135 each — dust against `MIN_ORDER_USD` and a 6× larger fill count for no informational gain. |
| `lookback` / `skip` | 252 / 21 sessions | The literature's 12-1 in sessions rather than calendar months, consistent with every other lookback in this repo. |
| `min_price` | $5 | Standard academic filter. `liquid` already floors at $3; $5 keeps a rank from being won by a low-priced name doubling on nothing. |
| `min_bars` | 253 | A name is either scored on the full window or excluded, never on a shorter one. |
| Return type | total | `base.total_return`'s convention (dividends as unreinvested cash), applied set-wide in SQL. Price-only would penalise every dividend payer against non-payers. |

## What changes vs `ew_benchmark`, and only that

The **ranking and eligibility rule**. Universe policy (today's `universe` flags),
basket size, weighting, cadence, fill model and dividend treatment are identical.

## Expectation, including the negative case

**If H0 holds** (the honest prior): median excess vs `ew_benchmark` near zero with a wide
CI, similar worst-fold drawdown, similar momentum crashes (2009-style, 2020-11, 2022).
Then the screen has been shown to be a complicated way to buy momentum, and every
"vs EW" verdict in the store is a "vs momentum" verdict — which is fine, but it should
be said that way.

**If the template adds value:** `ew_benchmark` beats this book on median excess with a
CI excluding zero *and* has a lower worst-fold drawdown. The template's trend-structure
conditions would then be worth their turnover and the screen's cost.

**If the control wins:** the screen *subtracts* from momentum — plausible, because the
template's "within 25% of 52-week high" and tight-base conditions select for
late-stage, lower-volatility momentum and the equal-weight top-50 of a 2.9k-name
universe is a far more concentrated bet on the extreme tail of the momentum
distribution. That tail is also where survivorship bias is largest (see below), so a
control win must be discounted before it is believed.

## Comparison

- **Primary:** `ew_benchmark`, identical folds, identical universe, median excess validate
  return, beat rate, worst-fold drawdown, 90% bootstrap CI.
- **Secondary:** `template_top10_banded` — the live template book with the most
  evidence. That spread measures the whole template *family* (screen + top-10
  concentration + banding) against plain momentum.
- Never against SPY alone: a survivor-universe single-name book vs an index is a universe
  comparison, and it flatters everything in this store.

## Kill criterion (verbatim from `configs.py`)

> Control: retired only once its question is answered. Kill if `ew_benchmark` beats it in
> ≥ 70% of walk-forward folds with a 90% CI on median excess that excludes 0 AND a lower
> worst-fold drawdown (screen shown to add value), or if any fold is inert, or if live max
> drawdown exceeds 55%.

The 55% line is deliberately looser than the template books' 40%: an unhedged top-50
momentum book has a documented −50%-class crash profile (2009), and killing the control
for behaving like momentum would defeat its purpose.

## Expected turnover

Roughly 30–40% of names replaced per month, i.e. **~4–5× equity one-way per year**.
Lower than `ew_benchmark` (whose passers churn on the screen's binary conditions) and far
below the weekly template books. At the fill model's 10–30 bp per side this is a
~2–3 pp/yr cost, similar in kind to EW's.

## Known biases, all inherited from the store

1. **Survivorship, and it scales with concentration.** `prices` holds only tickers listed
   today; `universe.active/liquid/etf` are today's flags (snapshots only since 2026-07-16).
   The top 50 of a 12-month return rank is *exactly* the population where delisting,
   acquisition and blow-up are most frequent, so this book inherits *more* survivor lift
   than a 50-name screen basket, not the same amount (`evaluation-2026-09-02.md` §2). A
   backtested edge over EW is therefore an upper bound; a backtested deficit is more
   credible than a surplus.
2. **Today's liquidity flag.** A name that is liquid in 2026 may have been a $6k/day
   micro-cap in 2023 — the 3y replay produced exactly one such `illiquid` rejection. The
   fill model's 1%-of-median-$vol guard catches the worst cases; it does not correct the
   selection.
3. **Fill model v2:** t+1 open, 10–30 bp per side by liquidity tier, no partial fills. A
   $39k book holding 50 names is small enough that the guard almost never binds; the live
   record will have the same cost structure as the backtest.
4. **Universe policy `all`:** leveraged ETNs filed as `etf = FALSE` could enter. None did in
   the 3y replay or on the 2026-09-01 signal; the `ex-leveraged` policy is not applied
   here because `ew_benchmark` does not apply it either, and the comparison must be
   like-for-like.

## First evidence — 3-year replay, run AFTER registration (2026-09-02)

Real `farm/backtest/replay.py` machinery against a read-only copy of the store,
window 2023-07-17 → 2026-07-16 (the farm's `3y`), fill model v2, policy `all`,
$39,000 notional. Controls re-run in the same session with identical code. One window;
**not** the 10-fold protocol, and the window is the strongest three momentum years since
2020. Numbers are context, not a verdict.

| book | total | CAGR | vol | Sharpe | max DD | worst month | fills | turnover (1-way/yr) |
|---|---|---|---|---|---|---|---|---|
| **xs_momentum_12_1** | +126.8% | +31.4% | 42.9% | 0.85 | −37.1% | −19.1% | 2,124 | 4.45 |
| ew_benchmark | +61.4% | +17.3% | 41.5% | 0.60 | −33.3% | −23.6% | 2,534 | 6.52 |
| template_top10_banded | −1.0% | −0.3% | 57.2% | 0.28 | −47.8% | −29.2% | 2,243 | 14.98 |
| spy_benchmark (context) | +71.3% | +19.7% | 15.0% | 1.28 | −18.4% | −5.5% | 1 | — |

Daily-return correlation with `ew_benchmark`: **0.87**. `ew_benchmark` beat the control
in **12 of 36** calendar months. Turnover came in at the expected ~4.5× and below EW's.

Reading, stated with the bias attached: on this window the unscreened control out-ran the
screen by 14 pp CAGR at 4 pp *more* drawdown, and out-ran the template family by 32 pp.
That is consistent with "the screen is momentum minus something", but the something may
well be survivorship lift concentrated in the control's tail. The 10-fold walk-forward
with the 90% CI is the pre-registered test; this table is not it.

## Prospective forward addendum — 2026-09-07

This addendum does not rewrite the 2026-09-02 charter or turn its historical evidence
into prospective evidence. The forward comparison was selected after inspecting the
three-year replay and walk-forward results. Those results are survivor-biased because
point-in-time `universe_snapshot` history begins only on 2026-07-16 (38 snapshots through
2026-09-04), so they motivated this test but cannot validate it.

The rule and comparison are frozen before `xs_momentum_12_1`'s first monthly signal:

- Candidate: `xs_momentum_12_1`; control: `ew_benchmark`; `$39,000` initial capital each.
- Signal boundary: 2026-09-30. Observation baseline: the first shared close after those
  next-open fills, expected 2026-10-01. The candidate must execute its first signal. An
  already-invested control may have an exact no-op rebalance; that no-op is recorded in
  the signal-boundary hash. The 2026-09-30 report must exist before the baseline can open;
  no return before the shared baseline is credited.
- Runtime: fill model `v4`, execution profile `baseline_v1`, profile SHA-256
  `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`.
  Candidate config SHA-256 is
  `fb5a0f0e3472f14ed9b0a5d5bac05a081ec0284f200db91663b11d5d47ab9214`; control config
  SHA-256 is `692d49494298d2e840c98ab78cb8e4a4829516b6049d7d24253eb3e28fe1318e`.
  The frozen runtime-contract v21 SHA-256 is
  `f7a8a048eb79643f244f08a40dbd328e299644452c03ef95907b6cf5db6c7fac`. It supersedes v20
  `8bdfdf2ce028964de6c49d10a95132ac66d66e5a900b4173109355e1945d781e` before the first signal
  for the isolated agent-paper lifecycle without changing the XS signal or economics. V20 superseded v19
  `7f4085fca17872a9ef1125c64ed03f58b2191abe68286e9720441df74f8f06f3` before the first signal
  so explicit DuckDB transactions clean up process-level interruptions without masking their
  original failure. V19 released temporary DataFrame views after failed statements. V18 superseded v17
  `4c6bfa198684a82bf05d500856039214a2ad105ab63afa107eb36603bae42906` before the first signal
  so the borrowed screen connection remains owned and closed exactly once by the outer runtime on
  the no-eligible exit. V17 made the non-derivable dated screen anchor precede row commit and made
  committed rows without it fail closed instead of being recomputed. V16 made idempotently skipped committed screen and league
  runs reconstruct their CSV, EOD, and report companions from ledger state. V15 made universe-cache, screen, league, and monthly walk-forward
  artifacts use same-directory atomic replacement. V14 made the daily screen and league connections
  close on every exit. V13 superseded v12
  `158ed6666d4005c9a555f41ea829925503214838199e4887acfc94169b9c32d9` so directory
  reconciliation and daily snapshot publication are one database transaction and
  the derived universe CSV is atomically replaced. Strategy, signal, execution economics, and
  statistical rules are unchanged. V12 made Nasdaq's plural security-class descriptions enforce
  the existing common-stock/ETF universe policy. V11 made
  every real weekly liquidity refresh retry the complete resumable pending backfill set, including
  on a zero-admission run. V10 keeps the existing no-same-bar fill rule active under
  optimized Python. V9
  excluded retired portfolio positions from current liquidity protection. V8
  made shared-metadata publication refuse malformed JSON instead of replacing it as an empty
  snapshot. V7 made an idempotently skipped screen validate its stored rows/report and restore
  their summary without rewriting history. V6 serialized concurrent metadata publication,
  routed the screener through the common merge helper, and froze that helper. V5 made EOD collection
  atomically preserve independently published miner, verification, and screen metadata. V4 made
  the weekly liquidity dry-run report its projected
  post-reconciliation count while leaving the store unchanged. V3 had made the EOD collector
  release DuckDB during Yahoo downloads, retries, and sleeps, with transactional backfill
  checkpoints. V2 had superseded
  `f88712e1ffdeead2fc640fad667531ac57a684651f887fd4ae525403231dcb7e` for corporate-action
  recovery. Candidate, control, signal date, execution, and statistical criteria are unchanged.
  Each migration was explicit and refused unless the exact prior checkpoint was still `WAITING`,
  had no signal boundary, and the store had no signal-date orders or post-fill observations.
- Inputs: the 2026-09-30 report records the complete `universe_snapshot` and
  `screen_results` hashes, the derived candidate ranks and control targets, both books'
  pre-trade state, and the exact pending intents. Those values cannot honestly be known
  before that future boundary. The 2026-10-01 report then records the exact fills, ledger
  prefix, and full baseline state. At both checkpoints, stored cash and equity must be
  finite and internally consistent with the current account and exact nonzero position
  rows; the stored position count must match those rows. The immutable ledger hash covers fills and any
  owner-entered settlements; late-arriving cash-dividend credits remain valid forward
  events rather than retroactive tampering. Every later report verifies the immutable
  boundary records and the full previously published equity prefix.
- Maturity: no earlier than 60 calendar months after 2026-10-01 and only with at least
  48 complete paired months. A month counts only when both books have the scheduled final
  NYSE-session mark; the open current month and any gap are excluded or fail closed.
- Primary gate: candidate total return > 0, cumulative candidate-minus-control return > 0,
  and the 90% stationary-bootstrap interval on mean paired monthly excess wholly > 0.
  The bootstrap uses 10,000 draws, mean block length four months, and seed `20260907`.
- Review/invalidity: candidate drawdown at or below −55%, or rejected/stale orders after
  the baseline, produces `REVIEW-KILL`. A rejected or mismatched initial transition,
  changed runtime/config/input hash, or rewritten equity prefix invalidates the record.

`engine.xs_forward_review` runs nightly and is read-only. `PASS-FORWARD` would support only
continued paper evaluation and human research review. It cannot promote a strategy,
change a portfolio, connect a broker, or authorize live capital; `automatic_action` is
always `none`.
