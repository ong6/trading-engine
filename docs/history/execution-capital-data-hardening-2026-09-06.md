# Execution, capital and data hardening — 2026-09-06

This is the implementation contract for the engine's three remaining research
touchpoints. It records measurements before changing the model. Nothing here is
a claim of live profitability and no live broker is connected.

## Current measured state

### Execution

- Signals are generated from session `t` closes and can fill only at a later
  session's open. Same-bar execution is rejected centrally.
- The current fill model charges 10/15/20/30 bp per side according to trailing
  60-session median dollar volume and rejects an order above 1% of that volume.
- Across the paper ledger's 975 fills, modeled price concession is **$3,553.46**
  on **$2,442,918.71** gross notional, or **14.55 bp** notional-weighted.
- The separate timing audit measures next-open versus signal-close drag. Its
  latest 975-fill estimate is +2.7 bp overnight and +17.4 bp all-in; the
  overnight estimate is noise (t=0.24).
- Missing today: explicit commission/minimum, regulatory/exchange fees,
  nonlinear participation impact, partial fills, borrow/short costs, taxes and
  ETF expense drag. The system is long-only, so borrow is currently irrelevant;
  taxes are account/jurisdiction-specific and should remain outside strategy
  alpha unless an account profile is selected.

### Capital and capacity

- Every current paper portfolio starts at **US$39,000** and permits fractional
  shares. Strategies size from current equity, so absent constraints percentage
  returns are mostly scale-invariant.
- Current observed order participation is small: median **0.0035%**, p95
  **0.0423%**, p99 **0.0758%**, maximum **0.1312%** of trailing median daily
  dollar volume. No current fill reaches the 1% rejection ceiling.
- Scaling the same orders linearly would produce approximately 60/975 orders
  above the 1% ceiling at $1m and 464/975 at $10m. Those are diagnostics, not a
  simulated capacity result: holdings, cash clamps and rejected orders would
  change the path.
- A capital study must therefore replay the complete strategy at each notional,
  not multiply the $39k result after the fact. Required grid:
  **$10k, $39k, $100k, $250k, $1m, $10m**. It must report returns, fills,
  rejected notional, maximum/p95 participation, turnover and modeled dollars of
  cost. No strategy may be called scalable above the largest passing notional.

### Data and what is being traded

- The store currently contains 19,965,368 daily rows for 12,105 symbols, all
  from yfinance; 26,660,522 intraday rows for 1,676 symbols; and 409,752
  corporate-action rows for 8,582 symbols.
- The independent Nasdaq verifier checked 3,945 of 4,100 selected liquid names
  on 2026-09-05: 3,939 agreed, 6 disagreed and 155 were not checked. A clean
  schema is not proof of a clean series: 423 daily rows violate ordinary OHLC
  containment, and 10 have a non-positive OHLC value.
- `universe_snapshot` is genuinely point-in-time but starts only 2026-07-16
  (38 dates through 2026-09-04). Historical stock membership before that date
  cannot be reconstructed from the current free sources.
- `spy_benchmark`, both dual-momentum variants, `sector_momentum`, the
  multi-asset trend strategy, and the sleeve-allocation strategies trade fixed ETF sets;
  their history is not exposed to single-stock survivor-universe selection.
  `macro_composite` holds SPY but consumes internally computed market breadth
  from today's surviving liquid universe, so its evidence class follows that
  survivor-biased input rather than the security ultimately held (and historical
  replay remains disabled until point-in-time macro inputs exist).
  `ew_benchmark`, template/momentum, mean-reversion, turtle, high-52-week,
  low-vol and cross-sectional momentum trade screen-derived stock/ETF baskets
  and inherit survivor bias historically. `low_vol` also uses a modern market
  cap snapshot. `xs_momentum_12_1` remains research-only for this reason.
- The current top-50 screen is not “the SPY”: it contains 45 non-ETFs and 5
  ETFs. The full active universe includes 821 leveraged/inverse instruments.
- Two verifier examples illustrate why disagreement classification matters:
  `VFLO` is plausible in Yahoo (~$55) while Nasdaq returns implausible ~$86k
  values with no volume, indicating a verifier/source-scale issue; `APH` has a
  genuine 2-for-1 split dated 2026-09-03 and the store contains isolated
  pre-split-scale bars immediately before it, which can contaminate signals.
  Neither ticker had an order, fill, pending order or open position at this
  checkpoint. An audited full-history `APH` refetch was then queued after the
  running read-only sweeps; `VFLO` was deliberately not auto-corrected. Any
  sweep completed before that repair is pre-repair evidence and must not be
  used for promotion. The later “Post-repair v4 walk-forward validation” section
  records completion and supersedes this point-in-time queued state.

## Required implementation gates

1. **Named execution profile.** Results record the complete cost assumptions,
   not only a fill-model version. At minimum: spread rule, fixed adverse bps,
   participation-impact function, commission/minimum/cap, sell-side fees,
   liquidity ceiling and fractional/whole-share policy.
2. **Per-portfolio starting capital.** Initial capital is persisted with each
   portfolio and used by replay, state rebuild, API return calculations and
   reports. It may not be inferred from a global constant after inception.
3. **Capital sensitivity artifacts.** Candidate promotion requires the capital
   grid above under baseline and 2x-cost stress. Results live outside canonical
   walk-forward files so sensitivity runs cannot overwrite baseline evidence.
4. **Data-quality class.** Every result is stamped as fixed-ETF/PIT, current-
   universe survivor-biased, or static-fundamental look-ahead. Reports must not
   silently compare classes as though their evidence quality were equal.
   Results also need a data snapshot fingerprint (at minimum price/action row
   counts, as-of dates and latest fetch watermark) so a repaired dataset cannot
   silently share a cohort with its predecessor.
5. **Price quarantine.** Material unresolved discontinuities affecting a held,
   pending or eligible symbol must be visible and must block a new entry. A
   cross-source disagreement alone is not enough to auto-correct data; source
   pathologies such as `VFLO` must not become destructive “repairs.”
6. **Promotion remains paper-only.** Passing simulations permits a longer
   forward paper trial, not live execution. A broker-specific profile requires
   an identified broker/account and reconciliation against its paper fills.

## Current assessment

The simulator is substantially stronger than a toy close-to-close backtest: it
has next-open execution, adverse spread/slippage, a capacity rejection, cash-
bounded pro-rata fills, corporate actions, dividends, stale marks and an
independent source verifier. It is not institution-grade: calibrated
broker/exchange fees and partial execution are absent, and historical
single-stock evidence is survivor-biased. Capital and execution assumptions are
now parameterized and stamped, but their sensitivity artifacts still have to
be generated for each candidate. ETF-only tests are the
cleanest historical evidence currently available; stock-basket results should
be treated as hypothesis generation until the forward point-in-time record is
long enough or a licensed survivorship-bias-free dataset is acquired.

## Measured five-year capital and cost sensitivity — 2026-09-07

All 48 cells below are complete day-step replays over 1,255 sessions, not
scaled returns. They share fill model `v4`, runtime-source hash
`0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262`
and repaired-data fingerprint
`b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.
Capacity statements are bounds at the six sampled balances, not interpolated
ceilings.

| Book | Evidence | $39k baseline CAGR | $39k 2x-cost CAGR | Turnover | Sampled capacity result |
|---|---|---:|---:|---:|---|
| `spy_benchmark` | fixed ETF | 12.85% | 12.84% | 0.99x | zero capacity rejects through $10m |
| `sector_momentum` | fixed ETF | 13.37% | 12.67% | 40.56x | zero rejects through $1m; rejects at $10m |
| `dual_momentum` | fixed ETF | 8.55% | 8.19% | 18.76x | zero rejects through $1m; rejects at $10m |
| `xs_momentum_12_1` | current-universe survivor-biased | 24.91% | 23.06% | 69.76x | no tested balance passes; rejects start at $10k |

The SPY control traded once and was invariant across capital. The ETF rotation
books were scale-invariant through $1m, then followed different, partially
unexecuted paths at $10m: sector rejected 18 attempts and dual momentum rejected
3 under baseline. Their apparently better or worse $10m returns are not
evidence that capital helps or hurts the rule; they are evidence that the rule
was no longer fully executed.

The stock-basket contrast exposed the stronger limitation. Baseline capacity
rejects rose from 4 at $10k to 315 at $1m and 1,734 at $10m. Its baseline CAGR
fell from 24.14% at $10k to 20.65% at $1m and 17.96% at $10m; at $10m,
$489.6m of intended notional was rejected. Those returns are survivor-biased
and increasingly liquidity-filtered, so they remain hypothesis-generation
evidence rather than a promotion case.

The aggregate writer now validates the exact six-capital by two-profile grid,
rejects mixed source/config/fill/policy/evidence/data cohorts, preserves the full
execution-profile stamp, reports market and total modeled costs separately, and
can rebuild summaries from validated cells without rerunning the strategies.

## Implemented hardening (fill model v4)

- `sim/execution.py` defines named, serialized profiles. `baseline_v1` exactly
  preserves the prior 10/15/20/30 bp-per-side behavior; `cost_2x_v1` doubles
  that market friction; `participation_stress_v1` adds deterministic square-root
  impact that reaches 10 bp at 1% participation. Broker commissions, minimums,
  caps and sell-side fees are separate profile fields and remain zero until an
  identified account schedule is verified.
- `portfolios.initial_cash` and `portfolios.execution_profile` persist each
  book's assumptions. Existing books migrate to `$39,000` and `baseline_v1`
  without changing current cash, positions, fills or equity. Rebuilds, APIs and
  league reports use the persisted capital.
- Each new fill has a companion `sim_fill_costs` row; every attempted execution
  has a `sim_execution_attempts` row. Capacity rejects retain raw notional and
  participation, while filled participation uses the quantity actually traded.
- Backtest and walk-forward results carry the full execution profile, starting
  capital, data-quality class and data snapshot fingerprint. Reports reject
  mixed source, fill-model, capital, profile, policy or snapshot cohorts and do
  not show relative comparisons across different evidence-quality classes,
  including the separate monthly walk-forward and continuous-proxy report.
- `farm.capital_sensitivity` performs the required six-capital grid under
  baseline and 2x costs as complete replays. Artifacts live under
  `data/reports/capital-sensitivity/`, never over canonical evidence.
- `price_quarantine` is explicitly adjudicated. Active rows block buys in both
  automated and discretionary paths while allowing exits. The verifier does not
  activate quarantine automatically: disagreement is evidence to investigate,
  not authority to repair or block.

Run the complete sensitivity grid for a candidate with:

```sh
.venv/bin/python -m farm.capital_sensitivity \
  --config xs_momentum_12_1 --window 5y
```

Revalidate completed cells and rebuild only their aggregate files with:

```sh
.venv/bin/python -m farm.capital_sensitivity \
  --config xs_momentum_12_1 --window 5y --rebuild-summary
```

Activate and later resolve a confirmed primary-data defect with:

```sh
.venv/bin/python -m engine.price_quarantine --ticker APH --activate \
  --reason 'confirmed split-scale corruption' --evidence 'manual primary-series audit'
.venv/bin/python -m engine.price_quarantine --ticker APH --resolve \
  --resolution 'audited full-history refetch and cross-source verification'
```

These controls improve simulation honesty; they do not establish live
profitability. Passing them permits further forward paper observation only.

## Post-repair v4 walk-forward validation — 2026-09-07

The disconnect-safe user service
`trading-engine-hardening-walkforward-20260907.service` completed all 18 active,
historically replayable books (queue jobs 356–373) and exited successfully.
Every result uses `$39,000`, `baseline_v1`, fill model `v4`, anchor
`2026-09-04`, repaired-data fingerprint
`b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`
and runtime-source hash
`f94c0c51b8bba9a94e4d874af008e48c1c437fd8535318e97a3e4b58addd6602`.
`sector_momentum` has nine valid folds because the first validate window opens
before its required ETF history begins; that fold is explicitly recorded as
dropped rather than silently shortened. The other 17 results contain all ten
terminal folds.

The fresh evidence does not justify promotion:

- `sector_momentum` remains WATCH and statistically indistinguishable from SPY:
  14.09% mean validate return, -1.17 percentage points mean excess over nine
  comparable folds, 90% fold CI [-6.50pp, +4.86pp]. Its monthly paired result
  is also indistinguishable (96 months, -0.14% mean excess/month, Newey-West
  t=-0.56).
- `dual_momentum` remains WATCH but its fold mean trails SPY: 9.67% mean
  validate return, -5.57pp mean excess, 90% fold CI [-10.49pp, -0.91pp]. The
  monthly mean is negative while the median is near zero, so the stricter
  monthly verdict remains INDISTINGUISHABLE rather than claiming a consistent
  loss.
- `xs_momentum_12_1` records 32.87% mean validate versus 26.45% for the
  equal-weight control, but its +6.42pp fold excess has a 90% CI of
  [-5.22pp, +15.78pp]. At monthly granularity it is also indistinguishable
  (120 months, +0.60% mean excess/month, Newey-West t=1.37, DSR 0.24). Both
  sides use today's surviving stock universe, and the separate capital study
  finds capacity rejects at every sampled balance, so this remains research
  evidence only.
- `mr_overlay` and `mr_overlay_gated` both trail the equal-weight control at
  monthly granularity. Their mean excess is approximately -1.72% and -1.74%
  per month respectively, with negative median intervals and Newey-West t below
  -2.7. The gate does not rescue the hypothesis.

The canonical fold report and per-book pages are in
`data/reports/walkforward/`; the paired monthly analysis is
`data/reports/walkforward/monthly-2026-09-07.md`. A post-render audit found and
fixed a parser that had shown blank fold-level verdicts after the evidence-class
column was introduced; the underlying simulation and statistical rows were not
affected.
