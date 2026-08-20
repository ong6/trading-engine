# Sweep — `meanrev`

_9 candidate(s) · **9 trials** · 10-fold protocol · generated 2026-08-20 19:23 UTC._

## Read this before the table

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+14.61%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `rsi_max-5__time_stop-10` | 10 | **-10.95%** | -18.95% | 0% | -19.55% |
| `rsi_max-5__time_stop-20` | 10 | **-11.18%** | -18.83% | 0% | -17.97% |
| `rsi_max-15__time_stop-10` | 10 | **-13.72%** | -21.68% | 0% | -23.45% |
| `rsi_max-5__time_stop-5` | 10 | **-13.78%** | -24.72% | 0% | -18.33% |
| `rsi_max-10__time_stop-10` | 10 | **-14.67%** | -21.88% | 0% | -17.95% |
| `rsi_max-10__time_stop-20` | 10 | **-14.74%** | -21.64% | 30% | -21.71% |
| `rsi_max-15__time_stop-20` | 10 | **-17.01%** | -24.05% | 0% | -22.52% |
| `rsi_max-15__time_stop-5` | 10 | **-19.02%** | -25.70% | 10% | -21.70% |
| `rsi_max-10__time_stop-5` | 10 | **-21.32%** | -25.22% | 10% | -22.60% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

