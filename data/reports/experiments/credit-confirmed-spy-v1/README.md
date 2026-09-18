# Credit-confirmed equity trend — historical result

Charter CREDIT-CONFIRMED-SPY-2026-09-18-v1 · decision REJECT-V1 · paper only · no automatic action.

One frozen candidate is compared with its per-fold exposure-matched SPY/BIL control. No grid or alternate parameter was run.

## Gates

| Gate | Result |
|---|---|
| baseline_cumulative_excess_positive | FAIL |
| baseline_minimum_effect_met | FAIL |
| baseline_mean_ci_above_zero | FAIL |
| cost_stress_excess_positive | FAIL |
| delay_stress_excess_positive | FAIL |
| drawdown_within_five_points_every_fold | FAIL |
| execution_data_and_accounting_clean | FAIL |

## Scenarios

| Scenario | Months | Candidate | Control | Excess | Mean excess/mo | 90% CI |
|---|---:|---:|---:|---:|---:|---:|
| baseline_v1 | 216 | +197.44% | +330.00% | -132.56% | -0.16% | [-0.34%, +0.02%] |
| cost_2x_v1 | 216 | +161.30% | +328.57% | -167.26% | -0.21% | [-0.40%, -0.04%] |
| delay_1_session_v1 | 216 | +179.37% | +331.64% | -152.27% | -0.19% | [-0.38%, +0.01%] |

A failed gate closes v1 without tuning. A pass permits only a separately frozen prospective paper comparison.
