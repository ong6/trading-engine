# Fixed-ETF rebalancing premium — historical charter result

_Charter `FIXED-ETF-REBAL-2026-09-07-v1` · decision **REJECT-V1** · paper only · no automatic action._

This is one pre-registered candidate/control comparison, not a parameter sweep. A historical pass would permit only a new shadow-paper registration.

## Gates

| Gate | Result |
|---|---|
| `baseline_cumulative_excess_positive` | PASS |
| `baseline_mean_ci_above_zero` | **FAIL** |
| `stress_cumulative_excess_positive` | PASS |
| `drawdown_within_five_points_every_fold` | PASS |
| `execution_and_accounting_clean` | PASS |

## Profile results

| Profile | Paired months | Candidate | Control | Cumulative excess | Mean excess/mo | 90% CI | Worst DD difference |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | 120 | +183.26% | +180.92% | +2.34% | +0.00% | [-0.05%, +0.06%] | -0.31% |
| `cost_2x_v1` | 120 | +182.82% | +180.94% | +1.88% | +0.00% | [-0.05%, +0.06%] | -0.31% |

A failure closes charter v1. It does not authorize asset substitution, cadence changes, threshold tuning, a new parameter grid, paper activation, or live capital.
