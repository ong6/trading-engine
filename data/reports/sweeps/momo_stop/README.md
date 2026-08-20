# Sweep — `momo_stop`

_9 candidate(s) · **9 trials** · 10-fold protocol · generated 2026-08-20 06:52 UTC._

## Read this before the table

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+14.61%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `n-20__stop_frac-0.9` | 10 | **-3.19%** | -4.08% | 30% | -42.76% |
| `n-10__stop_frac-0.9` | 10 | **-5.06%** | +1.85% | 50% | -52.47% |
| `n-20__stop_frac-0.85` | 10 | **-5.39%** | -4.20% | 30% | -45.05% |
| `n-20__stop_frac-0.8` | 10 | **-6.58%** | -5.86% | 20% | -45.57% |
| `n-5__stop_frac-0.85` | 10 | **-6.92%** | +8.67% | 40% | -63.72% |
| `n-10__stop_frac-0.85` | 10 | **-7.40%** | +1.82% | 30% | -48.01% |
| `n-5__stop_frac-0.9` | 10 | **-7.44%** | +13.97% | 40% | -63.43% |
| `n-10__stop_frac-0.8` | 10 | **-8.81%** | -0.05% | 30% | -49.73% |
| `n-5__stop_frac-0.8` | 10 | **-10.38%** | +8.11% | 40% | -65.45% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

