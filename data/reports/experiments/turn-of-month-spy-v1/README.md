# Turn-of-month SPY — historical charter result

_Charter `TURN-OF-MONTH-SPY-2026-09-07-v1` · decision **REJECT-V1** · paper only · no automatic action._

One frozen four-session calendar rule is compared with a static SPY/BIL control matched to its predeclared calendar exposure.

## Gates

| Gate | Result |
|---|---|
| `baseline_cumulative_excess_positive` | **FAIL** |
| `baseline_mean_ci_above_zero` | **FAIL** |
| `stress_cumulative_excess_positive` | **FAIL** |
| `drawdown_within_five_points_every_fold` | **FAIL** |
| `execution_data_and_accounting_clean` | **FAIL** |

## Profile results

| Profile | Paired months | Candidate | Control | Cumulative excess | Mean excess/mo | 90% CI | Worst DD difference |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | 120 | +12.98% | +61.30% | -48.31% | -0.28% | [-0.54%, -0.02%] | -9.35% |
| `cost_2x_v1` | 120 | -28.70% | +61.02% | -89.72% | -0.66% | [-0.92%, -0.39%] | -12.22% |

## Data boundary

The input contains 3,019 complete SPY/BIL sessions from 2014-09-04 through 2026-09-04; 577 are in-window. Exact bar fingerprint: `f9ec620a0265513a8535d9535c8d0a29ebb002feb3c57193e4d11a985152fcc4`.

A failed gate closes v1. A historical pass permits only a separately frozen shadow-paper comparison; neither outcome authorizes calendar tuning, automatic promotion, broker connectivity, or live capital.
