# 2022 agent replay

**CONTAMINATED RETROSPECTIVE DIAGNOSTIC - NOT ALPHA EVIDENCE.**

The current model may remember 2022 and the current-symbol archive is survivor-biased. No 2022 point-in-time fundamentals or timestamped news exist locally, so those variants are unavailable.

| Variant | Date | Choice | Prediction | Expected | Net return | SPY excess |
|---|---|---|---|---:|---:|---:|
| price_date_recall | 2022-01-31 | CASH | flat | +0.00% | +0.00% | +4.78% |
| price_date_recall | 2022-04-29 | CASH | flat | +0.00% | +0.00% | -0.57% |
| price_date_recall | 2022-07-29 | CASH | flat | +0.00% | +0.00% | +1.14% |
| price_date_recall | 2022-10-31 | CASH | flat | +0.00% | +0.00% | -1.10% |
| price_permuted | 2022-01-31 | XOM | up | +4.80% | +3.35% | +8.13% |
| price_permuted | 2022-04-29 | XOM | up | +3.50% | +14.57% | +14.00% |
| price_permuted | 2022-07-29 | XOM | up | +4.50% | +3.04% | +4.18% |
| price_permuted | 2022-10-31 | XOM | up | +4.50% | -1.83% | -2.93% |
| price_synthetic_perturbed | 2022-01-31 | MSFT | up | +3.50% | -5.17% | -0.39% |
| price_synthetic_perturbed | 2022-04-29 | AAPL | up | +4.50% | -4.70% | -5.28% |
| price_synthetic_perturbed | 2022-07-29 | MSFT | up | +3.50% | -3.70% | -2.56% |
| price_synthetic_perturbed | 2022-10-31 | MSFT | up | +4.50% | +2.24% | +1.14% |

## Summary

| Variant | Decisions | Accuracy | Mean net | Cumulative | Max DD | Mean excess vs SPY |
|---|---:|---:|---:|---:|---:|---:|
| price_date_recall | 4 | 100% | +0.00% | +0.00% | +0.00% | +1.06% |
| price_permuted | 4 | 75% | +4.78% | +19.78% | -8.20% | +5.85% |
| price_synthetic_perturbed | 4 | 25% | -2.83% | -11.02% | -17.27% | -1.77% |
