# VIX-term SPY timing — historical charter result

_Charter `VIX-TERM-SPY-2026-09-07-v1` · decision **REJECT-V1** · paper only · no automatic action._

One fixed VIX/VIX3M threshold is compared with a static SPY/BIL control matched to the signal's predeclared average equity exposure.

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
| `baseline_v1` | 120 | +117.74% | +261.17% | -143.43% | -0.42% | [-0.67%, -0.17%] | -8.47% |
| `cost_2x_v1` | 120 | +47.05% | +260.76% | -213.71% | -0.74% | [-1.03%, -0.46%] | -11.86% |

## Data boundary

The isolated reconstruction contains 3,019 joined VIX/VIX3M sessions from 2014-09-03 through 2026-09-03 (SHA-256 `f7a23f697acda36a8107b95516953ea40896219715b7abbc6b38b2be9af27c15`). Production macro history was not changed.

A failed gate closes v1. A historical pass permits only a separately frozen shadow-paper comparison; neither outcome authorizes parameter tuning, automatic promotion, broker connectivity, or live capital.
