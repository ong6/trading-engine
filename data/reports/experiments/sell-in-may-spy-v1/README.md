# Sell-in-May SPY — historical charter result

_Charter `SELL-IN-MAY-SPY-2026-09-07-v1` · decision **REJECT-V1** · paper only · no automatic action._

One frozen November-April rule is compared with a static SPY/BIL control matched to its predeclared calendar exposure.

## Gates

| Gate | Result |
|---|---|
| `baseline_cumulative_excess_positive` | **FAIL** |
| `baseline_mean_ci_above_zero` | **FAIL** |
| `stress_cumulative_excess_positive` | **FAIL** |
| `drawdown_within_five_points_every_fold` | **FAIL** |
| `execution_data_and_accounting_clean` | PASS |

## Profile results

| Profile | Paired months | Candidate | Control | Cumulative excess | Mean excess/mo | 90% CI | Worst DD difference |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | 120 | +99.38% | +139.83% | -40.45% | -0.12% | [-0.35%, +0.11%] | -16.30% |
| `cost_2x_v1` | 120 | +91.33% | +139.62% | -48.29% | -0.15% | [-0.38%, +0.07%] | -16.30% |

## Data boundary

The input contains 3,019 complete SPY/BIL sessions from 2014-09-04 through 2026-09-04; 1,480 are in November-April. Exact bar fingerprint: `f9ec620a0265513a8535d9535c8d0a29ebb002feb3c57193e4d11a985152fcc4`.

A failed gate closes v1. A historical pass permits only a separately frozen shadow-paper comparison; neither outcome authorizes calendar tuning, automatic promotion, broker connectivity, or live capital.
