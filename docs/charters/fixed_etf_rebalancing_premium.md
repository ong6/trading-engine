# Fixed-ETF rebalancing premium — completed research charter

Status: **completed 2026-09-07; REJECT-V1; not approved for the paper league**  
Charter ID: `FIXED-ETF-REBAL-2026-09-07-v1`  
Registered: 2026-09-07 UTC

## Question and mechanism

Can periodic equal-weight rebalancing across three imperfectly correlated liquid asset
classes earn positive net excess over owning the exact same starting basket without
rebalancing?

The proposed mechanism is volatility harvesting: fixed-weight rebalancing repeatedly sells
relative winners and replenishes relative losers while preserving broad diversification.
This is deliberately not another momentum lookback, trend gate, stop, volatility target, or
single-stock screen. The hypothesis can fail when trends persist, correlations rise, or
turnover costs exceed the rebalancing benefit.

## Frozen design before code or results

| Item | Declaration |
|---|---|
| Candidate ID | `fixed_etf_rebalanced` |
| Control ID | `fixed_etf_buy_hold` |
| Candidate | Equal-weight `SPY`, `IEF`, and `GLD`; after the shared initial entry, retarget one-third per asset only on the final tradable session of March, June, September, and December |
| Control | Buy the same three ETFs at equal target weights on the shared initial signal and never rebalance |
| Cash handling | Uninvested cash stays cash; dividends follow the simulator's existing corporate-action accounting |
| Universe | Exactly `SPY`, `IEF`, `GLD`; no substitutions, additions, or survivor screen |
| Capital | $39,000 at every independent fold start |
| Base costs | Complete `baseline_v1` execution-profile payload, captured in each result |
| Stress costs | Complete `cost_2x_v1` payload; sensitivity only, not a second chance to pass |
| Capacity | The selected profile's participation ceiling; any capacity rejection is reported |
| Data class | `fixed_etf_history`; the run records the full data-snapshot hash |
| Historical protocol | Anchor `2026-09-04`; 24-month train → 12-month validate, 12-month step, 10 folds |
| Trial count | One candidate and one control; no grid and no alternate cadence/asset set |
| Primary statistic | Mean paired monthly net excess return, candidate minus control, over validation months |
| Confidence method | 90% two-sided stationary-block-bootstrap percentile interval on that mean; geometric blocks averaging four months, 10,000 draws, seed `20260907` |

The train segment exists only to preserve the common replay protocol; neither strategy fits
parameters. The candidate and control must be generated from the same source hash, data
snapshot, fill model, capital, and execution profile. If any of those differ, there is no
comparison.

The paired monthly series is ordered by validation month across the non-overlapping folds.
“Cumulative paired validation excess” means
`product(1 + candidate_monthly_return) - product(1 + control_monthly_return)` over
that shared ordered series—not the difference between unpaired headline fold averages.
Missing months are excluded only as matched candidate/control pairs and must be counted in
the report. The confidence method and seed above are frozen; the existing Newey-West mean
t-statistic may be shown as a diagnostic but is not an alternate pass route.

## Frozen timing and failure semantics

- In every independent fold, both books issue their initial one-third-per-ETF targets from
  the first session's close and use the normal next-session-open fill path. “Inception” does
  not mean a same-bar fill.
- A quarter-end is the last NYSE session of March, June, September, or December. The
  candidate computes its new one-third targets at that close; resulting orders fill no
  earlier than the next session's open, normally in the next quarter. If the first session
  is itself a quarter-end, the shared initial entry is the only signal for that session.
- After initial entry, the control emits no more orders. Its dividends remain cash. The
  candidate's credited dividends are included in equity and may be redeployed at its next
  quarterly rebalance.
- All three tickers must have valid signal-date closes before either book emits its paired
  initial orders. A missing ticker causes no partial basket and must be reported. Later
  missing prices follow the common pending/rejection rules; unexplained asymmetry fails the
  charter rather than being imputed.
- Fractional quantities are allowed, as in the existing simulator. There is no tolerance
  band, drift trigger, alternate weighting rule, asset substitution, or calendar parameter.

Implementation uses the existing daily dispatcher plus a strategy-local quarter-end gate.
The two classes are absent from both the production registry and `CONFIGS`; the isolated
experiment process installs them only for the duration of its four frozen replays and
removes them even after a replay failure. Normal paper operation therefore cannot select
or create either book. Historical outputs live under
`data/reports/experiments/fixed-etf-rebalancing-v1/` and cannot overwrite the canonical
league walk-forward cohort.

## Historical decision rule

This first run is exploratory because the hypothesis was formed with knowledge of historical
markets. It may justify a new forward paper test only if all of the following hold under
`baseline_v1`:

1. cumulative paired validation excess is positive;
2. the 90% confidence interval on mean paired monthly excess lies wholly above zero;
3. excess remains positive under `cost_2x_v1`;
4. in no shared validation fold is candidate maximum drawdown more than 5 percentage points
   worse than the control's maximum drawdown in that same fold;
5. there are no unexplained missing fills, state mismatches, or capacity rejections.

Failure of any item closes this v1 hypothesis. There is no parameter search, asset swap,
cadence change, or post-result threshold adjustment under this charter.

## Result — 2026-09-07

**REJECT-V1.** All four frozen replays completed with 10 good folds, matching source/data/
protocol assumptions, no rejected or pending orders, no capacity failures, no missing
required prices or assets, and exact ledger rebuilds. The candidate's cumulative paired
validation excess was +2.34% under `baseline_v1` and +1.88% under `cost_2x_v1`, but baseline
mean monthly excess was only +0.0037% and its predeclared 90% stationary-bootstrap interval
was [-0.0517%, +0.0607%]. Because that interval includes zero, gate 2 failed and the charter
is closed without tuning or activation. See the generated
[`result report`](../../data/reports/experiments/fixed-etf-rebalancing-v1/README.md).

## Forward-entry and kill rules

Passing the historical rule permits only a new shadow-paper registration. It does not permit
promotion or live capital. That forward registration must start after implementation review,
freeze its own code/config/profile hashes and starting marks, and collect at least 24 quarterly
rebalance decisions or five calendar years, whichever is later. A safety review may stop it
early for a drawdown more than 10 percentage points worse than control or for any accounting
inconsistency; an early stop cannot be called a successful result.

At maturity, success requires positive cumulative net excess and a 90% interval on mean
paired monthly excess wholly above zero. Otherwise the strategy is rejected or remains
unproven. Historical performance cannot prove future profit, and no result from this charter
authorizes a broker connection or real-money trading.
