# Sweep — `voltarget`

_9 candidate(s) · **9 trials** · 10-fold protocol · generated 2026-08-19 04:44 UTC._

## Read this before the table

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+17.21%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `max_weight_mult-1.5__vol_lookback-120` | 10 | **+0.02%** | -1.80% | 50% | -35.70% |
| `max_weight_mult-1.5__vol_lookback-60` | 10 | **-0.01%** | -1.94% | 50% | -35.43% |
| `max_weight_mult-3.0__vol_lookback-60` | 10 | **-0.28%** | -1.84% | 50% | -35.38% |
| `max_weight_mult-3.0__vol_lookback-120` | 10 | **-0.45%** | -1.98% | 50% | -35.53% |
| `max_weight_mult-5.0__vol_lookback-120` | 10 | **-0.45%** | -1.98% | 50% | -35.53% |
| `max_weight_mult-5.0__vol_lookback-60` | 10 | **-0.56%** | -1.85% | 50% | -35.38% |
| `max_weight_mult-1.5__vol_lookback-20` | 10 | **-17.21%** | -23.75% | 30% | 0.00% |
| `max_weight_mult-3.0__vol_lookback-20` | 10 | **-17.21%** | -23.75% | 30% | 0.00% |
| `max_weight_mult-5.0__vol_lookback-20` | 10 | **-17.21%** | -23.75% | 30% | 0.00% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

