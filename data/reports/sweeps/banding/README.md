# Sweep — `banding`

_9 candidate(s) · **9 trials** · 10-fold protocol · generated 2026-08-20 06:52 UTC._

## Read this before the table

**Every row here is one of 9 parameter sets tried on the same data.** The best of N trials looks good at N=1 and looks good at N=60 for entirely different reasons, so the top row is NOT a finding — it is the starting point for one, and it has to survive a pre-registered forward test like anything else. Quote this table only with its trial count attached.

Ranked by **median** excess vs `ew_benchmark` on shared folds, not mean: at 6 folds the mean excess of every momentum book was carried entirely by the 2018-2021 window. Excess vs EW (same universe, same screen) is used rather than absolute return because it cancels most of the ~+7pp/yr survivorship inflation in this store.

Benchmark on these folds: median validate **+14.61%**, worst-fold drawdown **-37.53%**.

| Candidate | Folds | Median excess | Mean excess | Beats EW | Worst DD |
|---|---|---|---|---|---|
| `band_rank-15__n-5` | 10 | **-3.05%** | +15.05% | 50% | -61.32% |
| `band_rank-20__n-5` | 10 | **-3.39%** | +12.30% | 50% | -59.40% |
| `band_rank-30__n-5` | 10 | **-4.88%** | +8.51% | 40% | -57.88% |
| `band_rank-30__n-20` | 10 | **-5.64%** | -3.56% | 30% | -45.40% |
| `band_rank-15__n-10` | 10 | **-5.91%** | +1.84% | 30% | -49.14% |
| `band_rank-30__n-10` | 10 | **-7.05%** | -0.96% | 20% | -47.35% |
| `band_rank-15__n-20` | 10 | **-7.48%** | -3.77% | 20% | -45.72% |
| `band_rank-20__n-20` | 10 | **-7.48%** | -3.77% | 20% | -45.72% |
| `band_rank-20__n-10` | 10 | **-7.98%** | +3.25% | 30% | -48.61% |

## What a good row would look like

Positive median excess AND beats-EW comfortably above 50% AND a worst-fold drawdown no worse than the benchmark's. A row that is positive on median excess but beats EW in under half its folds is a skew bet, not an edge, and the distinction matters more than the headline number.

